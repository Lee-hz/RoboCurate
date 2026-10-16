"""Global sidebar, plain grade typography and horizontal review acceptance."""
import json
from pathlib import Path
from functools import partial
import tempfile
import threading
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import server as viewer
from studio import APP,StudioLibrary,Handler


def main():
    evidence=APP/'workspace/evidence';profiles=evidence/'profiles';profiles.mkdir(parents=True,exist_ok=True)
    real=StudioLibrary(APP/'workspace');before=real.store.all();checks=[]
    def check(name,ok):
        assert ok,name
        checks.append(name);print('PASS',name,flush=True)
    with tempfile.TemporaryDirectory(prefix='sidebar-ui-',dir=evidence) as tmp:
        lib=StudioLibrary(Path(tmp));(Path(tmp)/'cache').symlink_to(APP/'workspace/cache',target_is_directory=True)
        lib.add_root(APP.parent/'2026_09_10-17_40_44');lib.add_root(APP.parent/'mcap_viz.tar(1)/mcap_viz/mcap_0.mcap')
        viewer.STATIC_DIR=APP/'static';http=viewer.ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,library=lib,robot=viewer.Robot(APP/'robot/g1_29dof_rev_1_0.urdf')))
        threading.Thread(target=http.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{http.server_address[1]}'
        o=Options();o.add_argument('-headless');service=Service('/snap/bin/geckodriver',service_args=['--profile-root',str(profiles)],log_output=str(evidence/'sidebar-gecko.log'))
        d=webdriver.Firefox(options=o,service=service);wait=WebDriverWait(d,45)
        def js(code,*args):return d.execute_script(code,*args)
        def el(css):return d.find_element('css selector',css)
        def click(css):el(css).click()
        def side():return js('return document.documentElement.dataset.sidebar')
        def overflow():return js('return document.documentElement.scrollWidth>innerWidth')
        def record():
            d.get(url+'/#review/988e894e8afb')
            wait.until(lambda _:len(d.find_elements('css selector','[data-detail="diagnostics"]'))>0)
            click('[data-detail="diagnostics"]')
            wait.until(lambda _:len(d.find_elements('css selector','.event-list-row'))>0)
            wait.until(lambda _:js('return [...document.querySelectorAll("[data-camera]")].length===3 && [...document.querySelectorAll("[data-camera]")].every(i=>i.complete&&i.naturalWidth>0&&i.dataset.frameIndex!==undefined)'))
            js("window.shellErrors=[];addEventListener('error',e=>shellErrors.push(e.message));addEventListener('unhandledrejection',e=>shellErrors.push(String(e.reason)))")
        try:
            d.set_window_size(1580,1050);d.get(url);wait.until(lambda _:len(d.find_elements('css selector','.quality-card'))==5)
            check('expanded sidebar is explicit and accessible',side()=='expanded' and el('#sidebar-toggle').get_attribute('aria-expanded')=='true')
            check('grade navigation uses plain text without decorative icons',not d.find_elements('css selector','.quality-card svg') and len(d.find_elements('css selector','.quality-card .grade-code'))==4)
            check('published system font stack with normal weight',js('return getComputedStyle(document.body).fontFamily.includes("system-ui") && getComputedStyle(document.body).fontWeight==="400" && Number(getComputedStyle(document.querySelector("h1")).fontWeight)<=500'))
            check('sidebar toggle has explicit wording and a panel icon',el('#sidebar-toggle').text=='收起侧栏' and el('#sidebar-toggle use').get_attribute('href')=='/sidebar-control.svg#panel')
            current_url=d.current_url
            d.save_screenshot(str(evidence/'sidebar-library-expanded.png'))
            click('#sidebar-toggle')
            check('sidebar collapses to a navigable rail',side()=='collapsed' and js('return Math.round(document.querySelector(".sidebar").getBoundingClientRect().width)===56 && [...document.querySelectorAll("[data-nav]")].every(a=>a.getAttribute("aria-label")&&a.offsetWidth>0)'))
            check('sidebar control does not navigate back',d.current_url==current_url and el('#sidebar-toggle').text=='展开侧栏' and el('#sidebar-toggle use').get_attribute('href')=='/sidebar-control.svg#panel')
            check('content gains the released width',js('return parseFloat(getComputedStyle(document.querySelector(".app-shell")).marginLeft)===56'))
            d.save_screenshot(str(evidence/'sidebar-library-collapsed.png'))
            for view,selector in [('rules','.grade-standard'),('exports','#export-list'),('guide','.guide')]:
                click(f'[data-nav="{view}"]');wait.until(lambda _:bool(d.find_elements('css selector',selector)))
                check('collapse persists on '+view,side()=='collapsed' and el(f'[data-nav="{view}"]').get_attribute('aria-current')=='page')
                if view=='rules':
                    check('A to D standards contain no illustrated badge',not d.find_elements('css selector','.grade-standard svg') and len(d.find_elements('css selector','.grade-standard>.grade-code'))==4)
                    d.save_screenshot(str(evidence/'sidebar-rules-plain.png'))
            d.refresh();wait.until(lambda _:bool(d.find_elements('css selector','.guide')))
            check('sidebar preference survives reload',side()=='collapsed')
            d.set_window_size(1536,880);record()
            check('focus-only control has been removed',not d.find_elements('css selector','[data-action="focus"]') and not js('return document.body.classList.contains("focus-review")'))
            check('horizontal workspace follows available width',js('const a=document.querySelector(".playback-panel").getBoundingClientRect(),b=document.querySelector(".details-panel").getBoundingClientRect();return a.right<=b.left+1&&a.width>b.width&&b.width>=290'))
            check('summary metrics are folded by default',el('.diagnostic-overview').get_attribute('open') is None)
            click('.event-list-row')
            check('selected issue and decisions remain visible',js('const p=document.querySelector(".details-panel").getBoundingClientRect(),e=document.querySelector(".event-detail").getBoundingClientRect(),b=document.querySelector("[data-decision=confirmed]").getBoundingClientRect();return e.top>=p.top && b.top>=e.top && b.bottom<=e.bottom+1 && b.bottom<=innerHeight && document.querySelector("[data-decision=confirmed]").contains(document.elementFromPoint(b.x+b.width/2,b.y+b.height/2))'))
            wait.until(lambda _:js('return [...document.querySelectorAll("[data-camera]")].every(i=>Math.abs(Number(i.dataset.frameTime)-Number(document.querySelector("#timeline").value))<.15)'))
            print('EVENT_LAYOUT',js('return [".details-panel","#detail-body",".event-workspace",".event-list",".event-detail",".event-detail-content",".event-current-label",".event-title-line",".event-time",".event-detail-actions"].map(s=>{let e=document.querySelector(s),r=e.getBoundingClientRect(),c=getComputedStyle(e);return {s,top:r.top,h:r.height,scroll:e.scrollHeight,min:c.minHeight,max:c.maxHeight,flex:c.flex}})'),flush=True)
            check('event time remains visible above fixed actions',js('const a=document.querySelector(".event-time").getBoundingClientRect(),b=document.querySelector(".event-detail-content").getBoundingClientRect();return a.bottom<=b.bottom+1'))
            d.save_screenshot(str(evidence/'sidebar-review-selected.png'))
            before_time=float(el('#timeline').get_attribute('value'));click('#sidebar-toggle')
            check('resizing sidebar preserves review selection and time',side()=='expanded' and abs(float(el('#timeline').get_attribute('value'))-before_time)<1e-9 and len(d.find_elements('css selector','.event-list-row.selected'))==1)
            click('.detail-more>summary');click('[data-detail="signals"]');wait.until(lambda _:bool(d.find_elements('css selector','#signal-chart')))
            click('#sidebar-toggle')
            wait.until(lambda _:js('const c=document.querySelector("#signal-chart");return Math.abs(c.width-c.getBoundingClientRect().width*devicePixelRatio)<3'))
            check('signal canvas resizes with the shell',True)
            click('[data-detail="diagnostics"]')
            Select(el('#event-group')).select_by_value('right_arm')
            check('body filter stays accessible with metrics folded',all('右臂' in x.text for x in d.find_elements('css selector','.event-list-row')))
            click('.review-options>summary')
            click('.diagnostic-overview>summary');check('detailed body metrics remain available',len(d.find_elements('css selector','.body-metric'))==7)
            click('.diagnostic-overview>summary');click('.review-options>summary')
            click('[data-detail="review"]');el('#task-instruction').send_keys('仅用于隔离界面检查')
            ActionChains(d).key_down(Keys.CONTROL).send_keys('\\').key_up(Keys.CONTROL).perform()
            check('global shortcut preserves entered draft',side()=='expanded' and el('#task-instruction').get_attribute('value')=='仅用于隔离界面检查')
            click('#sidebar-toggle');d.set_window_size(1280,950)
            check('1280 collapsed review preserves visualization and evidence',js('const a=document.querySelector(".playback-panel").getBoundingClientRect(),b=document.querySelector(".details-panel").getBoundingClientRect();return a.right<=b.left+1') and not overflow())
            click('[data-detail="diagnostics"]');click('.event-list-row')
            wait.until(lambda _:js('return [...document.querySelectorAll("[data-camera]")].every(i=>Math.abs(Number(i.dataset.frameTime)-Number(document.querySelector("#timeline").value))<.15)'))
            d.save_screenshot(str(evidence/'sidebar-review-1280.png'))
            click('#theme-toggle');wait.until(lambda _:js('return document.documentElement.dataset.theme')=='light')
            d.save_screenshot(str(evidence/'sidebar-review-light.png'))
            check('no script errors during shell and horizontal review',js('return window.shellErrors')==[])
            d.set_window_size(700,1000);click('#sidebar-toggle')
            check('small-screen navigation opens as a drawer',side()=='expanded' and el('.sidebar-scrim').is_displayed() and not overflow())
            click('[data-nav="rules"]');wait.until(lambda _:len(d.find_elements('css selector','.grade-standard'))==4)
            check('choosing a page closes the mobile drawer',side()=='collapsed' and not el('.sidebar-scrim').is_displayed())
            click('#sidebar-toggle');ActionChains(d).send_keys(Keys.ESCAPE).perform()
            check('Escape closes the drawer and returns focus',side()=='collapsed' and js('return document.activeElement.id')=='sidebar-toggle')
            d.save_screenshot(str(evidence/'sidebar-rules-compact.png'))
            check('no real review data was modified',real.store.all()==before and not lib.store.all())
            (evidence/'sidebar-ui-result.json').write_text(json.dumps(dict(passed=True,checks=checks),ensure_ascii=False,indent=2))
        finally:
            try:d.save_screenshot(str(evidence/'sidebar-last-state.png'))
            except Exception:pass
            d.quit();http.shutdown();http.server_close();lib.pool.shutdown();lib.export_pool.shutdown()

if __name__=='__main__':main()
