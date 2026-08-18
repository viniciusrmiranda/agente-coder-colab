import streamlit as st
from groq import Groq
from duckduckgo_search import DDGS

st.set_page_config(page_title="Agente Coder", page_icon="🤖")
st.title("🤖 Agente Coder - Chat com Busca Web Automática")

# Puxa a chave dos Secrets do Streamlit de forma segura
api_key = st.secrets.get("GROQ_API_KEY")

if not api_key:
    st.error("Chave GROQ_API_KEY não configurada nos Secrets do Streamlit.")
    st.stop()

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Digite sua dúvida ou código..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Busca Web Automática em tempo real para TODA mensagem
    extra_context = ""
    try:
        with DDGS() as ddgs:
            results = [f"- {r['title']}: {r['body']}" for r in ddgs.text(user_input, max_results=3)]
            if results:
                extra_context = "\n\n--- Resultados da Busca na Web em Tempo Real ---\n" + "\n".join(results)
    except Exception as e:
        extra_context = f"\n[Busca na web temporariamente indisponível: {e}]"

    client = Groq(api_key=api_key)
    prompt_completo = user_input + extra_context
    
    messages_payload = [{"role": "system", "content": "Você é um assistente especialista em programação com acesso à internet em tempo real."}]
    for m in st.session_state.messages[:-1]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    messages_payload.append({"role": "user", "content": prompt_completo})

    with st.chat_message("assistant"):
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages_payload
        )
        bot_reply = response.choices[0].message.content
        st.markdown(bot_reply)

    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
