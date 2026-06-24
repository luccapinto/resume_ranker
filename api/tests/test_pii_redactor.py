import pytest
from api.redactor import PIIRedactor

# Define 15 synthetic Brazilian texts/resumes with diverse PII and VALID CPFs
TEST_RESUMES = [
    # 1. Simple resume with CPF, Name, Email, Phone
    """
    CURRÍCULO - João da Silva
    E-mail: joao.silva@email.com | Telefone: (11) 98765-4321
    CPF: 307.298.596-06 | RG: 12.345.678-9
    Endereço: Avenida Paulista, 1000 - São Paulo, SP
    Objetivo: Desenvolvedor Software Python
    """,
    # 2. Tech resume, unmasked CPF, different phone format
    """
    Ana Paula Souza
    Contato: +55 21 99999-8888 | anap@yahoo.com.br
    Documentos: CPF 61327335077 e RG 987654321
    Experiência na Google como Engenheira de Software.
    """,
    # 3. Project manager resume, landline, no country code
    """
    Pedro de Alcântara
    Residente em Belo Horizonte, MG.
    Telefone fixo: (31) 3456-7890. E-mail: pedro.pm@outlook.com
    CPF do candidato: 185.681.833-01
    """,
    # 4. Developer resume, no spaces in CPF, different phone punctuation
    """
    Maria Oliveira (maria.oli@gmail.com)
    Tel: 19-98888-7777. CPF: 62334902276. RG: 12345678-x
    Engenheira de Dados Senior, trabalhou na Microsoft em São Paulo.
    """,
    # 5. Intern resume, multiple emails, unmasked phone
    """
    Carlos Eduardo Santos | carlos.edu@gmail.com | carlos_santos@company.com
    Cel: 11977776666 | CPF: 270.662.207-57
    Estudante de Engenharia na USP.
    """,
    # 6. Consultant resume, spaces in phone, masked RG
    """
    Juliana Mendes - consultora.j@mendes.adv.br
    Telefone: +55 (81) 96666 5555
    CPF: 097.996.758-98 | RG: 45.678.901-2
    Localização: Recife, PE
    """,
    # 7. Analyst resume, masked/unmasked combinations
    """
    Roberto Carlos
    CPF: 029.476.603-07, RG: 23.456.789-X, E-mail: rcarlos@show.com.br
    Tel: (21) 2555-5555. Rio de Janeiro, RJ.
    """,
    # 8. Designer resume, email in text, phone with 3 digit DDD prefix
    """
    Beatriz Souza | bia.design@behance.net
    Telefone: 011 95555-4444
    CPF: 81948212900
    Endereço: Curitiba, PR
    """,
    # 9. QA resume, different spaces and format
    """
    Marcos Vinicius Santos
    E-mail: marcos.qa@test.com
    Tel: (41) 94444-3333 | CPF: 560.420.462-50
    Cidade: Porto Alegre - RS
    """,
    # 10. Architect resume, international format phone
    """
    Fernanda Lima
    Email: fernanda.arq@uol.com.br | Fone: +55 (61) 93333-2222
    CPF: 738.409.505-03 | RG: 34.567.890-1
    Brasília, DF.
    """,
    # 11. Support tech resume, unmasked CPF and RG
    """
    Lucas Costa (lucas.costa@suporte.com.br)
    Celular: 85922221111 | CPF: 74429868115 | RG: 1234567
    Fortaleza, CE.
    """,
    # 12. Director resume, spaces around separators
    """
    Gabriela Montenegro
    Contato: gaby.montenegro@corp.com - (31) 91111-0000
    CPF: 998.791.229 - 09 | RG: 56 . 789 . 012 - 3
    Trabalhou na Ambev.
    """,
    # 13. Coordinator resume, only numbers in document
    """
    Tiago Alves - tiago.alves@hotmail.com
    Tel: 71 98888 9999
    Documento CPF: 94358739792. Salvador, BA.
    """,
    # 14. Specialist resume, parentheses phone
    """
    Patricia Araujo
    Email: patricia.s@tech.io | Fone: (92)98111-2222
    CPF: 29330467091
    Manaus, AM.
    """,
    # 15. Executive resume
    """
    Eduardo Ramos | eduardo.ramos@exec.com
    Telefone: 11 97000-0000 | CPF: 097.231.589-65
    São Paulo, SP.
    """
]

def test_pii_redactor_basic_redaction():
    redactor = PIIRedactor()
    text = "Meu nome é João da Silva, meu CPF é 307.298.596-06, meu e-mail é joao@email.com e meu telefone é (11) 98765-4321."
    
    redacted, r_map = redactor.redact(text)
    
    # Assert placeholders are present
    assert "[NOME_REDACT_1]" in redacted
    assert "[CPF_REDACT_1]" in redacted
    assert "[EMAIL_REDACT_1]" in redacted
    assert "[TELEFONE_REDACT_1]" in redacted
    
    # Assert values are anonymized
    assert "João da Silva" not in redacted
    assert "307.298.596-06" not in redacted
    assert "joao@email.com" not in redacted
    assert "(11) 98765-4321" not in redacted
    
    # Check map
    assert r_map["[NOME_REDACT_1]"] == "João da Silva"
    assert r_map["[CPF_REDACT_1]"] == "307.298.596-06"
    assert r_map["[EMAIL_REDACT_1]"] == "joao@email.com"
    assert r_map["[TELEFONE_REDACT_1]"] == "(11) 98765-4321"

def test_pii_redactor_evaluation_on_15_resumes():
    redactor = PIIRedactor()
    
    # We will evaluate recall and precision for CPF and Email
    # since we know the exact ground truth values in our synthetic resumes.
    
    # Let's define the exact expected CPFs and Emails in each resume index:
    ground_truth = [
        {"cpfs": ["307.298.596-06"], "emails": ["joao.silva@email.com"]},
        {"cpfs": ["61327335077"], "emails": ["anap@yahoo.com.br"]},
        {"cpfs": ["185.681.833-01"], "emails": ["pedro.pm@outlook.com"]},
        {"cpfs": ["62334902276"], "emails": ["maria.oli@gmail.com"]},
        {"cpfs": ["270.662.207-57"], "emails": ["carlos.edu@gmail.com", "carlos_santos@company.com"]},
        {"cpfs": ["097.996.758-98"], "emails": ["consultora.j@mendes.adv.br"]},
        {"cpfs": ["029.476.603-07"], "emails": ["rcarlos@show.com.br"]},
        {"cpfs": ["81948212900"], "emails": ["bia.design@behance.net"]},
        {"cpfs": ["560.420.462-50"], "emails": ["marcos.qa@test.com"]},
        {"cpfs": ["738.409.505-03"], "emails": ["fernanda.arq@uol.com.br"]},
        {"cpfs": ["74429868115"], "emails": ["lucas.costa@suporte.com.br"]},
        {"cpfs": ["998.791.229 - 09"], "emails": ["gaby.montenegro@corp.com"]}, # Note potential spaces
        {"cpfs": ["94358739792"], "emails": ["tiago.alves@hotmail.com"]},
        {"cpfs": ["29330467091"], "emails": ["patricia.s@tech.io"]},
        {"cpfs": ["097.231.589-65"], "emails": ["eduardo.ramos@exec.com"]}
    ]
    
    total_expected_cpfs = 0
    total_detected_cpfs = 0
    false_positive_cpfs = 0
    
    total_expected_emails = 0
    total_detected_emails = 0
    false_positive_emails = 0
    
    for i, resume in enumerate(TEST_RESUMES):
        gt = ground_truth[i]
        expected_cpfs = gt["cpfs"]
        expected_emails = gt["emails"]
        
        total_expected_cpfs += len(expected_cpfs)
        total_expected_emails += len(expected_emails)
        
        redacted_text, redaction_map = redactor.redact(resume)
        
        # Verify that all expected CPFs and emails are NOT in the redacted text
        # and are correctly captured in the redaction map
        detected_values = list(redaction_map.values())
        
        # Check CPFs
        for exp_cpf in expected_cpfs:
            clean_exp = "".join(c for c in exp_cpf if c.isdigit())
            
            found = False
            for det_val in detected_values:
                clean_det = "".join(c for c in det_val if c.isdigit())
                if clean_exp == clean_det:
                    found = True
                    break
            
            if found:
                total_detected_cpfs += 1
                
        # Check Emails
        for exp_email in expected_emails:
            found = exp_email.lower() in [v.lower() for v in detected_values]
            if found:
                total_detected_emails += 1
                
        # Calculate false positives: items recognized as CPF/EMAIL that are not CPF/EMAIL
        for placeholder, original in redaction_map.items():
            if "CPF" in placeholder:
                clean_orig = "".join(c for c in original if c.isdigit())
                # Check if this clean_orig matches any expected cpf
                if not any("".join(c for c in exp if c.isdigit()) == clean_orig for exp in expected_cpfs):
                    false_positive_cpfs += 1
            elif "EMAIL" in placeholder:
                if original.lower() not in [e.lower() for e in expected_emails]:
                    false_positive_emails += 1
                    
    # Calculate Precision and Recall
    cpf_recall = total_detected_cpfs / total_expected_cpfs
    cpf_precision = total_detected_cpfs / (total_detected_cpfs + false_positive_cpfs) if total_detected_cpfs > 0 else 0
    
    email_recall = total_detected_emails / total_expected_emails
    email_precision = total_detected_emails / (total_detected_emails + false_positive_emails) if total_detected_emails > 0 else 0
    
    print(f"CPF Recall: {cpf_recall:.2%}, CPF Precision: {cpf_precision:.2%}")
    print(f"Email Recall: {email_recall:.2%}, Email Precision: {email_precision:.2%}")
    
    # Assert precision and recall are >= 95% (or 0.95)
    assert cpf_recall >= 0.95
    assert cpf_precision >= 0.95
    assert email_recall >= 0.95
    assert email_precision >= 0.95

def test_pii_redactor_initialization_exception():
    # Attempting to load with an invalid spaCy model should raise RuntimeError
    with pytest.raises(RuntimeError) as exc_info:
        from unittest.mock import patch
        with patch("presidio_analyzer.nlp_engine.nlp_engine_provider.NlpEngineProvider.create_engine", side_effect=Exception("Model not found")):
            PIIRedactor()
            
    assert "Failed to initialize PII Redactor" in str(exc_info.value)
