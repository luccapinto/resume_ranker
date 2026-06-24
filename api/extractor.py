import os
import json
import httpx
from typing import Type, TypeVar
from pydantic import BaseModel
from api.config import settings

T = TypeVar('T', bound=BaseModel)

class OpenRouterExtractor:
    def __init__(self, api_key: str = None, default_model: str = None):
        # Allow passing key/model directly, otherwise fallback to settings/env
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.model = default_model or os.getenv("OPENROUTER_MODEL", "google/gemini-2.5-pro")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def extract(self, text: str, schema_class: Type[T]) -> T:
        """
        Extracts structured data from redacted text according to the provided Pydantic schema using OpenRouter.
        """
        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise ValueError(
                "OpenRouter API Key not configured. Please set the OPENROUTER_API_KEY environment variable or pass it to the constructor."
            )

        # Generate JSON schema from Pydantic model for structured outputs
        json_schema = schema_class.model_json_schema()
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/luccapinto/resume_ranker",
            "X-Title": "Resume Ranker Extraction API"
        }
        
        system_prompt = (
            "Você é um assistente de IA especialista em recrutamento e seleção de talentos técnicos. Sua tarefa é analisar o texto de um currículo ou de uma vaga de emprego (que foi previamente higienizado e anonimizado) e extrair de forma estruturada as informações necessárias para preencher o perfil padronizado.\n\n"
            "Instruções críticas:\n"
            "1. Mapeie a senioridade para uma das seguintes categorias do enum: 'Estágio', 'Júnior', 'Pleno', 'Sênior' ou 'Especialista/Lead'.\n"
            "2. Mantenha os nomes das competências (skills_raw) fiéis ao que está escrito no currículo bruto (ex: 'JS', 'ReactJS', 'Python 3', 'Kubernetes'). Não tente normalizá-las ou traduzi-las agora.\n"
            "3. Calcule com precisão os anos totais de experiência profissional baseando-se nos anos e meses descritos em cada cargo. Evite contar em dobro períodos sobrepostos. Se não houver experiência profissional clara, retorne 0.0.\n"
            "4. Consolide as responsabilidades e o escopo de atuação profissional no campo `narrative_experience`. Escreva um parágrafo longo e rico contendo a história profissional do candidato/vaga.\n"
            "5. Se o texto contiver tokens de anonimização (ex: [NOME_REDACT_1], [LOCALIZACAO_REDACT_2], etc.), mantenha esses tokens exatamente como estão. Não tente desanonimizá-los ou inferir dados reais sobre eles."
        )
        
        user_prompt = f"Por favor, analise e extraia as informações estruturadas do seguinte texto de currículo ou vaga:\n\n---\n{text}\n---"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_class.__name__,
                    "schema": json_schema,
                    "strict": True
                }
            },
            "temperature": 0.1
        }
        
        max_retries = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Use a generous timeout since LLM generation + structured output mapping can take time
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(self.api_url, headers=headers, json=payload)
                    
                    if response.status_code != 200:
                        raise ValueError(f"OpenRouter API returned error status {response.status_code}: {response.text}")
                        
                    response_json = response.json()
                    
                    if "choices" not in response_json or not response_json["choices"]:
                        raise ValueError(f"Empty choices in OpenRouter response: {response_json}")
                        
                    content_str = response_json["choices"][0]["message"]["content"]
                    
                    # Parse structure and validate using Pydantic schema model
                    extracted_data = json.loads(content_str)
                    return schema_class.model_validate(extracted_data)
                    
            except Exception as e:
                last_error = e
                # Wait briefly before retrying
                import time
                time.sleep(1.0 * (attempt + 1))
                
        raise RuntimeError(
            f"Failed to extract structured data after {max_retries} attempts. Last error: {str(last_error)}"
        )
