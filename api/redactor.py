import re
from typing import List, Dict, Any, Tuple
from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer, IpRecognizer

# Define Brazilian Entity Recognizers

class CPFRecognizer(PatternRecognizer):
    def __init__(self):
        patterns = [
            # Masked CPF: 123.456.789-00, allows optional spaces
            Pattern(name="cpf_masked", regex=r"\b\d{3}\s*\.\s*\d{3}\s*\.\s*\d{3}\s*-\s*\d{2}\b", score=0.95),
            # Unmasked CPF: 12345678900
            Pattern(name="cpf_unmasked", regex=r"\b\d{11}\b", score=0.7),
        ]
        super().__init__(
            supported_entity="CPF",
            patterns=patterns,
            supported_language="pt",
            context=["cpf", "cadastro de pessoas fisicas", "documento", "identificacao"]
        )

    def validate_cpf(self, text: str) -> bool:
        # Extract digits
        digits = [int(c) for c in text if c.isdigit()]
        if len(digits) != 11:
            return False
        
        # Check if all digits are equal (e.g. 111.111.111-11 is invalid but matches regex)
        if len(set(digits)) == 1:
            return False
            
        # Validate first digit
        sum1 = sum(digits[i] * (10 - i) for i in range(9))
        d1 = (sum1 * 10) % 11
        if d1 >= 10:
            d1 = 0
        if d1 != digits[9]:
            return False
            
        # Validate second digit
        sum2 = sum(digits[i] * (11 - i) for i in range(10))
        d2 = (sum2 * 10) % 11
        if d2 >= 10:
            d2 = 0
        if d2 != digits[10]:
            return False
            
        return True

    def analyze(self, text, entities, nlp_artifacts=None):
        results = super().analyze(text, entities, nlp_artifacts)
        validated_results = []
        for result in results:
            value = text[result.start:result.end]
            if self.validate_cpf(value):
                result.score = 0.95
                validated_results.append(result)
        return validated_results


class RGRecognizer(PatternRecognizer):
    def __init__(self):
        patterns = [
            # Masked RG: e.g., 12.345.678-9, 1.234.567-8, 12.345.678-x, 12.345.678-X
            Pattern(name="rg_masked", regex=r"\b\d{1,2}\.\d{3}\.\d{3}-[0-9xX]\b", score=0.95),
            # Unmasked RG or different separators: e.g., 123456789, 12345678X, 12345678-9
            Pattern(name="rg_semi_masked", regex=r"\b\d{7,10}-[0-9xX]\b", score=0.8),
            Pattern(name="rg_unmasked", regex=r"\b\d{7,10}\b", score=0.5),
        ]
        super().__init__(
            supported_entity="RG",
            patterns=patterns,
            supported_language="pt",
            context=["rg", "registro geral", "identidade", "carteira", "documento", "emissor"]
        )


class BrazilPhoneRecognizer(PatternRecognizer):
    def __init__(self):
        patterns = [
            # DDD of 2 digits + 9 digits (cellphone) or 8 digits (landline)
            # Handles: +55 (11) 98765-4321, 11987654321, (11) 98765-4321, 011 98765-4321, etc.
            # Removed leading word boundary to correctly match starting parentheses
            Pattern(
                name="br_phone_with_ddd",
                regex=r"(?:\+?55\s?)?\(?(?:0?[1-9][1-9])\)?\s?(?:9\d{4}-?\d{4}|\d{4}-?\d{4})\b",
                score=0.95
            ),
            # Local phone numbers without DDD: 98765-4321, 3456-7890
            Pattern(
                name="br_phone_local",
                regex=r"\b(?:9\d{4}-?\d{4}|[2-9]\d{3}-?\d{4})\b",
                score=0.6
            )
        ]
        super().__init__(
            supported_entity="PHONE_NUMBER",
            patterns=patterns,
            supported_language="pt",
            context=["telefone", "celular", "fone", "contato", "whatsapp", "call", "phone", "tel"]
        )


class PIIRedactor:
    def __init__(self):
        try:
            # Set up the spacy NLP engine using pt_core_news_lg
            configuration = {
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "pt", "model_name": "pt_core_news_lg"}],
            }
            provider = NlpEngineProvider(nlp_configuration=configuration)
            nlp_engine = provider.create_engine()
            
            # Initialize Analyzer with pt-specific engine
            self.analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["pt"])
            
            # Remove the default PhoneRecognizer as it conflicts with BrazilPhoneRecognizer and matches CPFs
            self.analyzer.registry.remove_recognizer("PhoneRecognizer")
            
            # Enable default Email and IP recognizers for Portuguese
            email_rec = EmailRecognizer()
            email_rec.supported_language = "pt"
            self.analyzer.registry.add_recognizer(email_rec)
            
            ip_rec = IpRecognizer()
            ip_rec.supported_language = "pt"
            self.analyzer.registry.add_recognizer(ip_rec)
            
            # Register custom Brazilian recognizers
            self.analyzer.registry.add_recognizer(CPFRecognizer())
            self.analyzer.registry.add_recognizer(RGRecognizer())
            self.analyzer.registry.add_recognizer(BrazilPhoneRecognizer())
            
        except Exception as e:
            # Propagate and raise initialization exceptions for fail-fast
            raise RuntimeError(f"Failed to initialize PII Redactor: {str(e)}") from e

    def redact(self, text: str) -> Tuple[str, Dict[str, str]]:
        """
        Redacts PII from the given text and replaces sensitive fields with structured tokens.
        Returns a tuple of (redacted_text, redaction_map) where redaction_map maps
        the placeholders (e.g. [NOME_REDACT_1]) back to the original values.
        """
        if not text:
            return "", {}

        # Analyze the text for PII
        # We look for standard entities plus our custom CPF and RG
        entities_to_detect = [
            "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CPF", "RG", 
            "IP_ADDRESS", "LOCATION", "ORGANIZATION"
        ]
        
        results = self.analyzer.analyze(
            text=text,
            language="pt",
            entities=entities_to_detect
        )
        
        # Sort results from left to right to allocate stable IDs
        left_to_right = sorted(results, key=lambda x: x.start)
        
        # Define clean readable names for the placeholders
        entity_name_map = {
            "PERSON": "NOME_REDACT",
            "EMAIL_ADDRESS": "EMAIL_REDACT",
            "PHONE_NUMBER": "TELEFONE_REDACT",
            "CPF": "CPF_REDACT",
            "RG": "RG_REDACT",
            "IP_ADDRESS": "IP_REDACT",
            "LOCATION": "LOCALIZACAO_REDACT",
            "ORGANIZATION": "ORGANIZACAO_REDACT"
        }
        
        redacted_text = text
        redaction_map = {}
        entity_counters = {}
        placeholders = []
        
        for res in left_to_right:
            original_val = text[res.start:res.end]
            entity_type = res.entity_type
            
            # Map standard entity type to customized clean tag
            clean_tag = entity_name_map.get(entity_type, entity_type)
            
            if clean_tag not in entity_counters:
                entity_counters[clean_tag] = 1
            else:
                entity_counters[clean_tag] += 1
                
            idx = entity_counters[clean_tag]
            placeholder = f"[{clean_tag}_{idx}]"
            placeholders.append((res.start, res.end, placeholder, original_val))
            
        # Apply replacements from right to left to ensure offsets remain valid
        for start, end, placeholder, original_val in reversed(placeholders):
            redacted_text = redacted_text[:start] + placeholder + redacted_text[end:]
            redaction_map[placeholder] = original_val
            
        return redacted_text, redaction_map
