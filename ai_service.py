import os
import json
import requests
from typing import Dict, Any, List

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

MODELS = [
    "gemini-3.8-flash",
    "gemini-2.5-flash",
    "gemini-1.5-flash",
    "gemini-flash-latest"
]

def generate_viral_content(
    title: str,
    duration: int,
    is_short: bool,
    transcript: str = "",
    past_scripts: List[str] = None
) -> Dict[str, Any]:
    past_context = ""
    if past_scripts:
        past_context = "ROTEIROS JÁ GERADOS ANTERIORMENTE (NÃO REPITA ESTAS IDEIAS NEM GANCHOS):\n" + "\n".join(f"- {s}" for s in past_scripts[:10])

    prompt = f"""
Você é um estrategista e roteirista mestre em vídeos virais de TikTok, Instagram Reels e YouTube Shorts focado no nicho de cheats, utilitários, dicas e mods de jogos.
Seu objetivo é prender a atenção no primeiro segundo, reter até o fim e converter visualizações em seguidores/cliques.

DADOS DO VÍDEO ORIGINAL:
- Título do vídeo: {title}
- Duração: {duration} segundos ({'Short / Rápido' if is_short else 'Vídeo Longo'})
- Transcrição / Legenda: {transcript if transcript else 'Não disponível (crie um roteiro criativo baseado no título e tema do jogo)'}

{past_context}

INSTRUÇÕES OBRIGATÓRIAS:
1. GANCHOS (HOOKS): Crie 3 variações diferentes e apelativas de gancho para os primeiros 3 segundos.
   - Gancho 1: Quebra de padrão / choque.
   - Gancho 2: Segredo / revelação ("Eles não querem que você saiba...").
   - Gancho 3: Solução para dor ("Cansado de perder ranqueada?").
2. CORPO (ROTEIRO): Roteiro dinâmico, direto ao ponto, com instruções de cortes e tela (ex: [Corta pra tela do jogo], [Mostra o placar]). Se for para vídeo de 1 a 2 min, divida em etapas rápidas.
3. CTA (CHAMADA PRA AÇÃO): CTA matador focado em comentários ou link na bio.
4. PROMPTS DE CAPA:
   - 1 prompt detalhado para gerar imagem de capa no Midjourney / Bing / DALL-E.
   - Texto sugerido em letras grandes para colocar por cima da capa.

RESPONDA EXCLUSIVAMENTE EM FORMATO JSON VÁLIDO COM ESTA ESTRUTURA:
{{
  "hook_1": "texto do gancho 1",
  "hook_2": "texto do gancho 2",
  "hook_3": "texto do gancho 3",
  "body": "texto completo do roteiro com orientações visuais",
  "cta": "texto do CTA",
  "prompt_thumb": "descrição do prompt para IA de imagem",
  "thumb_overlay_text": "texto curto e impactante para escrever na thumbnail"
}}
"""

    for model_name in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.8,
                "responseMimeType": "application/json"
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=25)
            if r.status_code == 200:
                data = r.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Clean markdown backticks if any
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                return json.loads(text.strip())
        except Exception as e:
            continue

    # Resilient fallback if offline/error
    return {
        "hook_1": f"Se você joga isso, pare tudo o que está fazendo agora!",
        "hook_2": f"Eles tentaram esconder esse truque da ranqueada de todo mundo...",
        "hook_3": f"Você ainda joga no modo padrão? Dá uma olhada no que acontece com isso aqui.",
        "body": f"[00:00 - 00:03] Gancho visual no gameplay.\n[00:03 - 00:15] Mostra a diferença absurda de desempenho.\n[00:15 - 00:40] Passo a passo rápido de como configurar ou ativar sem complicação.\n[00:40 - 00:50] Gameplay insana final com o resultado.",
        "cta": "Link direto tá no primeiro comentário ou na bio. Corre antes que tirem do ar!",
        "prompt_thumb": f"Dark cyber gamer room, glowing neon cyan and purple, aggressive gamer character with HUD holographic overlay, high contrast, 8k resolution, cinematic lighting.",
        "thumb_overlay_text": "APELÃO DEMAIS!"
    }
