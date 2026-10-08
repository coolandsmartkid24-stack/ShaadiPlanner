"""Builds ../demo.html: the real App.jsx compiled with esbuild + an in-browser copy of the API logic over embedded data."""
import json, re, subprocess, pathlib
root = pathlib.Path(__file__).parent.parent
app = (root / "frontend/src/App.jsx").read_text()
app = re.sub(r'^import .*$', '', app, flags=re.M).replace("export default function App", "function App")
app = 'const {useEffect,useMemo,useState}=React;\n' + app + '\nReactDOM.createRoot(document.getElementById("root")).render(React.createElement(App));'
(root / "tools/_app.jsx").write_text(app)
js = subprocess.run(["node_modules/.bin/esbuild", "tools/_app.jsx".replace("tools/", ""), "--minify", "--loader:.jsx=jsx"], cwd=root / "tools", capture_output=True, text=True, check=True).stdout
keep = ("id","name","sections","city","area","rating","reviews","score","phone","address","hours","website","category","lat","lon","maps_url","review_text")
rows = json.loads((root / "backend" / "places.json").read_text())
rows = [{k: r[k] for k in keep} for r in rows]
for r in rows:
    r["address"] = r["address"][:120]; r["hours"] = r["hours"][:140]; r["review_text"] = r["review_text"][:200]
css = (root / "frontend/src/styles.css").read_text()
api = r'''
const ROWS=%s;
const SECTIONS={venue:"Marquee / Venue",planner:"Event planner",makeup:"Parlour / Makeup",dj:"DJ / Sound",photo:"Photographer",sweets:"Sweets"};
const km=(a,b)=>{const R=Math.PI/180,h=Math.sin((b[0]-a[0])*R/2)**2+Math.cos(a[0]*R)*Math.cos(b[0]*R)*Math.sin((b[1]-a[1])*R/2)**2;return 12742*Math.asin(Math.sqrt(h))};
let PLAN="free";
const api={demo:true,setPlan:p=>{PLAN=p},
 meta:async()=>{const o={};ROWS.forEach(r=>{(o[r.city]=o[r.city]||{});o[r.city][r.area]=(o[r.city][r.area]||0)+1});
  const cities={};for(const c in o)cities[c]=Object.keys(o[c]).filter(a=>a!=="Other areas").sort((a,b)=>o[c][b]-o[c][a]);return{vendors:ROWS.length,sections:SECTIONS,cities}},
 plan:async(city,area,minRating=0)=>{const sections=[];
  for(const code in SECTIONS){const pool=ROWS.filter(r=>r.city===city&&r.sections.includes(code));const here=pool.filter(r=>r.area===area);
   const pts=ROWS.filter(r=>r.city===city&&r.area===area&&r.lat);const c=pts.length?[pts.reduce((s,r)=>s+r.lat,0)/pts.length,pts.reduce((s,r)=>s+r.lon,0)/pts.length]:null;
   const all0=null;const near=pool.filter(r=>r.area!==area&&r.lat&&c&&km(c,[r.lat,r.lon])<=12).sort((a,b)=>b.score-a.score);
   const al=here.concat(near),rr=al.filter(r=>r.rating).map(r=>r.rating);const stats={count:al.length,avg:rr.length?rr.reduce((a,b)=>a+b,0)/rr.length:0,reviews:al.reduce((a,r)=>a+(r.reviews||0),0)};
   if(PLAN!=="premium"){const by=l=>l.filter(r=>r.rating).sort((a,b)=>a.rating-b.rating||a.reviews-b.reviews);const low=by(here)[0]||by(near)[0];
    sections.push({code,label:SECTIONS[code],available:here.length+near.length,stats,lowest:low?{rating:low.rating,phone:low.phone,area:low.area}:null})}
   else{const top=here.sort((a,b)=>b.score-a.score).concat(near).filter(r=>(r.rating||0)>=minRating).slice(0,5);
    sections.push({code,label:SECTIONS[code],available:here.length+near.length,stats,vendors:top.map(r=>({...r,in_area:r.area===area}))})}}
  return{plan:PLAN,city,area,sections}}};
''' % json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
html = f'''<title>Shaadi Planner</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap">
<style>{css}</style>
<div id="root"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.3.1/umd/react.production.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.3.1/umd/react-dom.production.min.js"></script>
<script>{api}</script>
<script>{js}</script>
'''
(root / "demo.html").write_text(html)
print(len(html) // 1024, "KB")
