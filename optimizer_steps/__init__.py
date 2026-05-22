"""
optimizer_steps — Optimization_Tool.py monolitiğinden çıkarılan yardımcı
modüller.

Sprint 2 #8: 2,889 satırlık Optimization_Tool.py modülerleşmesi. İlk adım
Excel report writer'ını ayrı bir modüle çekmek (~415 satır). Sonraki
sprintlerde Step 1-4 render fonksiyonları da buraya taşınabilir.

Tasarım kararı: Streamlit'in script-rerun davranışı nedeniyle bu modüller
"safe to import + idempotent render" beklentisi taşır. session_state'e
yazıyorsa rerun sonrası mantıklı duruma gelmeli.
"""
