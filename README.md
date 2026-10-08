# Shaadi Planner
1. Crawl daily:      python google_places_crawler.py --import existing.tsv --loop 1440
2. Sort / rank:     python sort_places.py <existing.tsv | islamabad_rawalpindi_places_progress.json>    (writes backend/places.json)
3. API:             cd backend && pip install -r requirements.txt && uvicorn main:app --reload     (demo logins: free@demo.pk/free, premium@demo.pk/premium)
4. Web app:         cd frontend && npm install && npm run dev                                       (http://localhost:5173)
Free plan: the server returns only area name + lowest rating + phone per section. Premium: 5 ranked vendors per section with full details.
Plan is decided by the signed token on the server. Replace USERS in backend/main.py with a real database and payment webhook.
Rerun step 2 whenever the crawler adds data; the API reloads backend/places.json automatically.

## ChatGPT layer (backend/llm.py)
export OPENAI_API_KEY=sk-...   (optional: OPENAI_MODEL, MAX_LLM_CALLS_PER_DAY)
POST /api/ask {"text": "..."}  ->  rules parse the sentence for free; ChatGPT only if the area/section is missing;
Premium also gets ONE batched web-search call that verifies phone, capacity, price, hours, website, Instagram for the top 5 (cached 30 days).
Warm the cache overnight:  cd backend && python llm.py warm venue 40
