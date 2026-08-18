import streamlit as st
from groq import Groq
from duckduckgo_search import DDGS

st.set_page_config(page_title="Agente Coder", page_icon="🤖")
st.title("🤖 Agente Coder - Chat & Busca Web")

api_key = st.sidebar.text_input("Cole sua API Key da Groq:", type="password")
enable_web = st.sidebar.checkbox("Ativar Busca na Web (DuckDuckGo)")

if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if user_input := st.chat_input("Digite sua dúvida ou código..."):
    if not api_key:
        st.error("Insira sua chave de API da Groq na barra lateral para continuar.")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    extra_context = ""
    if enable_web:
        try:
            with DDGS() as ddgs:
                results = [f"- {r['title']}: {r['body']}" for r in ddgs.text(user_input, max_results=3)]
                extra_context = "\n\n--- Busca Web ---\n" + "\n".join(results)
        except Exception as e:
            extra_context = f"\n[Erro na busca web: {e}]"

    client = Groq(api_key=api_key)
    prompt_completo = user_input + extra_context
    
    messages_payload = [{"role": "system", "content": "Você é um assistente especialista em programação."}]
    for m in st.session_state.messages[:-1]:
        messages_payload.append({"role": m["role"], "content": m["content"]})
    messages_payload.append({"role": "user", "content": prompt_completo})

    with st.chat_message("assistant"):
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages_payload
        )
        bot_reply = response.choices[0].message.content
        st.markdown(bot_reply)

    st.session_state.messages.append({"role": "assistant", "content": bot_reply})
