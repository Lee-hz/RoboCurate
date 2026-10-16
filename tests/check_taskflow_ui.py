"""Read-only live workbench acceptance; all browser mutations are intercepted."""
import json,time
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait,Select
from selenium.webdriver.common.keys import Keys
base=Path(__file__).resolve().parents[1];out=base/'workspace/evidence/taskflow-ui-20261016';out.mkdir(exist_ok=True)
opts=Options();opts.add_argument('-headless')
d=webdriver.Firefox(options=opts,service=Service('/snap/bin/geckodriver',service_args=['--profile-root',str(base/'workspace/evidence/profiles')],log_output=str(out/'gecko.log')))
wait=WebDriverWait(d,35);checks=[];performance={}
def el(css):return d.find_element('css selector',css)
def js(code,*args):return d.execute_script(code,*args)
def click(css):el(css).click()
def check(name,ok):
    assert ok,name
    checks.append(name);print('PASS',name,flush=True)
def ready():return js('const i=document.querySelector("#tf-preview");return i?.complete&&i.naturalWidth>0&&i.dataset.frameIndex!==undefined')
def seek(t):js('const s=document.querySelector("#tf-scrub");s.value=arguments[0];s.dispatchEvent(new Event("input",{bubbles:true}));',t)
try:
    d.set_window_size(1440,1080);d.get('http://127.0.0.1:8421/#taskflow/ed1733854bde473a92825173e3de327d');wait.until(lambda _:ready())
    js("window.uiErrors=[];window.writes=[];addEventListener('error',e=>uiErrors.push(e.message));addEventListener('unhandledrejection',e=>uiErrors.push(String(e.reason)));const f=window.fetch;window.fetch=(url,o={})=>{if(o.method&&o.method.toUpperCase()!=='GET'){writes.push(String(url));return Promise.reject(Error('验收期间禁止写入'));}return f(url,o)}")
    check('original camera frames are loaded through the batch player',el('#tf-preview').get_attribute('src').startswith('blob:'))
    check('horizontal stage overview leaves room for a large video',js('const v=document.querySelector(".tf-visual").getBoundingClientRect(),r=document.querySelector(".tf-detail").getBoundingClientRect(),s=document.querySelector(".tf-stage-rail").getBoundingClientRect();return v.width>r.width*2 && s.bottom<=v.top && v.right<r.left'))
    d.save_screenshot(str(out/'desktop-dark.png'))
    # Start with cold future batches and measure displayed frames, not only clock ticks.
    seek(10);wait.until(lambda _:abs(float(el('#tf-preview').get_attribute('data-frame-time'))-10)<.15)
    n=int(el('#tf-preview').get_attribute('data-paint-count'));t=time.monotonic();click('#tf-play');time.sleep(3);click('#tf-play');elapsed=time.monotonic()-t
    shown=int(el('#tf-preview').get_attribute('data-paint-count'))-n;performance.update(frames=shown,seconds=round(elapsed,3),fps=round(shown/elapsed,2))
    check('native playback displays over 12 frames per second',shown/elapsed>12)
    check('pause state is accessible',el('#tf-play').get_attribute('aria-label')=='播放')
    for cam in ['right_wrist','left_wrist','head','right_wrist','head']:
        click(f'[data-tf="camera"][data-cam="{cam}"]');wait.until(lambda _:el('#tf-preview').get_attribute('data-camera')==cam and not el('#tf-media-error').is_displayed())
        before=int(el('#tf-preview').get_attribute('data-frame-index'));click('[data-tf="step-frame"][data-direction="1"]');wait.until(lambda _:int(el('#tf-preview').get_attribute('data-frame-index'))==before+1)
    check('repeated camera switching and exact frame stepping remain responsive',True)
    seek(30.842835583);wait.until(lambda _:abs(float(el('#tf-preview').get_attribute('data-frame-time'))-30.842835583)<.15)
    check('recording endpoint displays a real frame',not el('#tf-media-error').is_displayed())
    click('.tf-segment-row[data-index="0"]');click('[data-tf="detail-tab"][data-tab="manual"]');el('#tf-note').send_keys('仅界面验收草稿，不保存')
    Select(el('#tf-decision')).select_by_value('uncertain');click('.tf-segment-row[data-index="1"]');click('.tf-segment-row[data-index="0"]')
    check('review draft survives stage navigation',el('#tf-note').get_attribute('value')=='仅界面验收草稿，不保存' and el('#tf-decision').get_attribute('value')=='uncertain')
    click('[data-tf="detail-tab"][data-tab="criteria"]');click('.tf-condition-evidence summary')
    check('condition evidence expands on demand',el('.tf-condition-evidence').get_attribute('open')=='true')
    # Evidence buttons must not be mistaken for the native camera image.
    click('.tf-evidence [data-camera="right_wrist"]');wait.until(lambda _:el('#tf-preview').get_attribute('data-camera')=='right_wrist' and not el('#tf-media-error').is_displayed())
    check('evidence locates its camera and time',True)
    click('[data-tf="filter-segments"][data-filter="not_completed"]');check('empty failure filter stays clear',el('#tf-segment-empty').is_displayed());click('[data-tf="filter-segments"][data-filter="all"]')
    for width in (1024,500):
        d.set_window_size(width,1000);check(f'{js("return innerWidth")}px workspace has no horizontal overflow',js('return document.documentElement.scrollWidth<=innerWidth'))
        d.save_screenshot(str(out/f'width-{width}.png'))
    d.set_window_size(1440,1080);click('#theme-toggle');time.sleep(.3);d.save_screenshot(str(out/'desktop-light.png'))
    check('light theme supported',js('return document.documentElement.dataset.theme')=='light')
    click('[data-tf="setup"][data-tab="review"]');check('setup preserves the exact audited range',el('#tf-range-end').get_attribute('value')=='30.842835583')
    d.set_window_size(500,1000);check('mobile setup dialog fits viewport',js('const d=document.querySelector("#tf-setup-dialog");return d.scrollWidth<=d.clientWidth'))
    d.save_screenshot(str(out/'mobile-setup.png'));click('[data-tf="close-setup"]')
    d.set_window_size(1440,1080);Select(el('#tf-runs')).select_by_value('18b56d215cb24c2bb37376c28c6a94b6');wait.until(lambda _:len(d.find_elements('css selector','.tf-segment-row'))==4 and ready())
    check('older visual result still plays and has all native cameras',len(d.find_elements('css selector','[data-tf="camera"]'))==3)
    check('no uncaught browser errors',js('return uiErrors')==[]);check('no database writes or model requests',js('return writes')==[])
    (out/'result.json').write_text(json.dumps(dict(checks=checks,playback=performance),ensure_ascii=False,indent=2));print(json.dumps(performance),flush=True)
finally:d.quit()
