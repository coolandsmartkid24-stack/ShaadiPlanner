from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':1200,'height':1000}); errs=[]
    pg.on('pageerror',lambda e: errs.append(str(e)))
    pg.goto('file:///home/claude/shaadi/tools/test.html'); pg.wait_for_selector('.card')
    pg.screenshot(path='a.png')
    for t in ["I live in G-9 Islamabad, 400 guests, I need a photographer","bridal makeup in Saddar Rawalpindi","mithai near dha phase 2 for 500 people","hello"]:
        pg.fill('#ask',t); pg.click('.go')
        print(t,'->',[pg.input_value(i) for i in ('#f-city','#f-area','#f-guests','#f-sec')], pg.inner_text('.note') if pg.query_selector('.note') else '')
    pg.fill('#ask',"I live in F-7 Islamabad, my guests are 696, I want a marquee near me"); pg.click('.go')
    pg.click('.seg button:has-text("Premium")'); pg.wait_for_selector('.vendor'); pg.screenshot(path='b.png')
    pg.set_viewport_size({'width':400,'height':900}); print(errs, pg.evaluate('document.documentElement.scrollWidth')); pg.screenshot(path='m.png')
