"""Make the synthetic corpus internally consistent and PII-realistic.

The generator produces good prose but sloppy identifiers: it reuses the same
handful of names across résumés, writes `123.456.789-00` as everyone's CPF —
which fails the check-digit validation, so the redactor correctly ignores it —
and gives everyone the same phone number. That silently guts the anonymisation
demo: there is nothing valid left to redact.

This pass rewrites the identity of each résumé from an explicit, distinct
table: full name, matching e-mail, a *valid* CPF with correct check digits, and
a plausible mobile number. It is idempotent and deterministic — running it twice
produces the same corpus.

    python -m api.eval.normalize_seed_corpus [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from typing import Dict, List, Optional, Tuple

# Progress must reach a redirected log immediately; block buffering makes these
# scripts look frozen for the twenty minutes they take to run.
sys.stdout.reconfigure(line_buffering=True)

SEED_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "seed", "candidates"
)

# One distinct identity per résumé. Fictional, but plausible for a Brazilian pool.
IDENTITIES: Dict[str, str] = {
    "ana-kafka": "Ana Beatriz Mendes",
    "bruno-airflow": "Bruno Tavares Nogueira",
    "carla-analytics-eng": "Carla Siqueira Prado",
    "diego-dba": "Diego Ramalho Bastos",
    "eduarda-streaming": "Eduarda Kimura Sales",
    "felipe-fullstack": "Felipe Moreira Rangel",
    "gabriela-frontend": "Gabriela Portela Aguiar",
    "henrique-backend-java": "Henrique Barbosa Vidal",
    "isabela-fullstack-junior": "Isabela Fontenele Cruz",
    "joao-fullstack-senior": "João Vitor Caldeira",
    "karina-llm": "Karina Yamamoto Brito",
    "leonardo-cv": "Leonardo Sampaio Duarte",
    "mariana-mlops": "Mariana Vasconcelos Reis",
    "nicolas-cientista": "Nicolas Ferraz Quintela",
    "olivia-bi-junior": "Olívia Machado Pontes",
    "paulo-estagio-bi": "Paulo Sérgio Bittencourt",
    "renata-comercial": "Renata Bandeira Nunes",
    "sergio-financeiro": "Sérgio Antunes Cavalcanti",
    "tatiana-sre": "Tatiana Rezende Peixoto",
    "ulisses-devops": "Ulisses Amorim Botelho",
    "vanessa-platform": "Vanessa Lobato Guedes",
    "wagner-infra": "Wagner Pimentel Braga",
    "xavier-pm-fintech": "Xavier Andrade Lacerda",
    "yara-po": "Yara Bittar Monteiro",
    "zeca-ux": "José Carlos Tenório",
    "amanda-marketing": "Amanda Vilela Peçanha",
    "beatriz-juridico": "Beatriz Coutinho Serra",
    "caio-logistica": "Caio Mesquita Fialho",
}

EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
PHONE_RE = re.compile(r"(?:\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}-?\d{4}")

DDDS = [11, 21, 31, 41, 47, 48, 51, 61, 62, 71, 81, 85]
CITIES = [
    "São Paulo, SP", "Rio de Janeiro, RJ", "Belo Horizonte, MG", "Curitiba, PR",
    "Florianópolis, SC", "Joinville, SC", "Porto Alegre, RS", "Brasília, DF",
    "Goiânia, GO", "Salvador, BA", "Recife, PE", "Fortaleza, CE",
]


def cpf_check_digits(base: List[int]) -> Tuple[int, int]:
    """The two CPF verification digits for a 9-digit base."""
    first = (sum(d * (10 - i) for i, d in enumerate(base)) * 10) % 11
    first = 0 if first >= 10 else first

    second_base = base + [first]
    second = (sum(d * (11 - i) for i, d in enumerate(second_base)) * 10) % 11
    second = 0 if second >= 10 else second
    return first, second


def make_cpf(index: int) -> str:
    """A valid, formatted CPF, distinct per index.

    The 9-digit base comes from a small linear congruential generator so that
    consecutive indices do not collapse onto the same digits.
    """
    state = (index + 1) * 2_654_435_761 % 1_000_000_007
    base: List[int] = []
    for _ in range(9):
        state = (state * 1_103_515_245 + 12_345) % 2_147_483_648
        base.append(state % 10)
    if len(set(base)) == 1:  # all-equal CPFs are invalid by rule
        base[0] = (base[0] + 1) % 10
    d1, d2 = cpf_check_digits(base)
    digits = "".join(map(str, base))
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{d1}{d2}"


def make_phone(index: int) -> str:
    ddd = DDDS[index % len(DDDS)]
    middle = (index * 7919 + 1234) % 10000
    tail = (index * 104729 + 4321) % 10000
    return f"({ddd}) 9{middle:04d}-{tail:04d}"


def slugify(name: str) -> str:
    ascii_name = "".join(
        c for c in unicodedata.normalize("NFD", name) if unicodedata.category(c) != "Mn"
    )
    parts = [p.lower() for p in re.split(r"\s+", ascii_name) if len(p) > 2]
    return f"{parts[0]}.{parts[-1]}" if len(parts) > 1 else (parts[0] if parts else "candidato")


def current_name(text: str) -> Optional[str]:
    """The name currently written at the top of the résumé, if any."""
    from api.ats import _titleize, looks_like_person_name

    for line in text.splitlines()[:4]:
        stripped = line.strip()
        if looks_like_person_name(stripped):
            return _titleize(stripped)
    return None


def normalize(dry_run: bool = False) -> None:
    files = sorted(f for f in os.listdir(SEED_DIR) if f.endswith(".txt"))
    seen_cpfs: Dict[str, str] = {}

    for index, filename in enumerate(files):
        slug = filename[: -len(".txt")]
        path = os.path.join(SEED_DIR, filename)
        text = open(path, encoding="utf-8").read()

        new_name = IDENTITIES.get(slug)
        if not new_name:
            print(f"· {filename}: sem identidade definida, ignorado")
            continue

        old_name = current_name(text)
        updated = text
        if old_name and old_name != new_name:
            # Replace the full name in every casing, then any later reference to
            # the given name on its own ("Lucas liderou…").
            for variant, replacement in (
                (old_name, new_name),
                (old_name.upper(), new_name.upper()),
            ):
                updated = updated.replace(variant, replacement)
            given_old, given_new = old_name.split()[0], new_name.split()[0]
            updated = re.sub(rf"\b{re.escape(given_old)}\b", given_new, updated)

        email = f"{slugify(new_name)}@email.com"
        cpf = make_cpf(index)
        phone = make_phone(index)
        city = CITIES[index % len(CITIES)]

        updated = EMAIL_RE.sub(email, updated, count=1)
        updated = CPF_RE.sub(cpf, updated, count=1)
        updated = PHONE_RE.sub(phone, updated, count=1)

        if cpf in seen_cpfs:
            raise RuntimeError(f"CPF duplicado entre {seen_cpfs[cpf]} e {filename}: {cpf}")
        seen_cpfs[cpf] = filename

        print(f"✓ {filename:32} {new_name:28} {cpf}  {phone}  {city}")
        if not dry_run and updated != text:
            open(path, "w", encoding="utf-8").write(updated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    normalize(dry_run=args.dry_run)
