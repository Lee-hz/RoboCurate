"""Browser acceptance using real read-only inputs and an isolated review DB."""
import copy
import json
from functools import partial
from pathlib import Path
import shutil
import tempfile
import threading
import urllib.request

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import Select, WebDriverWait

from studio import StudioLibrary, Handler
import server as viewer

APP=Path(__file__).resolve().parents[1]
EP='511aac43933e'
MODEL='g1-stage-v3'


def main():
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(url):
        with opener.open(url,timeout=30) as response:return json.load(response)
    original=get(f'http://127.0.0.1:8421/api/progress?ep={EP}&model_id={MODEL}')
    models=get('http://127.0.0.1:8421/api/progress/models')
    models['models']=[m for m in models['models'] if m['id']==MODEL]
    source=APP.parent/'2026_09_10-17_40_44/data/lenovo/v141_smoke/episode_000131/mcap/mcap_0.mcap'
    source_before=(source.stat().st_size,source.stat().st_mtime_ns)
    out=APP/'workspace/evidence/execution-quality';out.mkdir(parents=True,exist_ok=True)
    profiles=out/'browser-profiles';profiles.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='execution-quality-') as tmp:
        lib=StudioLibrary(Path(tmp)/'workspace');lib.add_root(source);lib.default_id=EP
        ref=lib.ref(EP);cache=lib.cache_dir(ref);cache.mkdir(parents=True)
        for name in ('meta.json','native.npz','series.f32'):
            shutil.copy2(APP/'workspace/cache'/cache.name/name,cache/name)
        lib.progress_service.current=lambda ep,model:copy.deepcopy(original)
        lib.progress_service.models=lambda:copy.deepcopy(models)
        http=viewer.ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,library=lib,robot=viewer.Robot(APP/'robot/g1_29dof_rev_1_0.urdf')))
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(http.server_address[1])
        def report():return get(base+f'/api/execution-quality?ep={EP}&model_id={MODEL}')
        opts=Options();opts.add_argument('-headless')
        driver=webdriver.Firefox(options=opts,service=Service('/snap/bin/geckodriver',service_args=['--profile-root',str(profiles)],log_output=str(out/'gecko.log')))
        wait=WebDriverWait(driver,45);checks=[]
        def el(css):return driver.find_element('css selector',css)
        def js(code,*args):return driver.execute_script(code,*args)
        def click(css):
            element=el(css);js("arguments[0].scrollIntoView({block:'center'})",element);element.click()
        def check(name,value):
            assert value,name
            checks.append(name);print('PASS',name,flush=True)
        def fill(css,value):
            js("arguments[0].value=arguments[1];arguments[0].dispatchEvent(new Event('input',{bubbles:true}))",el(css),value)
        def choose(css,value):
            Select(el(css)).select_by_value(value)
        def open_phase(i):
            css=f'[data-execution-phase="phase-{i}"]'
            js('arguments[0].open=true',el(css))
            return css
        def save(css,revision):
            click(css+' [data-execution-save]')
            wait.until(lambda _:report()['review']['revision']==revision)
            wait.until(lambda _:'已保存' in el(css+' [data-execution-dirty]').text)
        try:
            driver.set_window_size(1580,1050);driver.get(base+f'/#review/{EP}')
            wait.until(lambda _:driver.find_elements('css selector','[data-detail=progress]'))
            js("window.executionErrors=[];addEventListener('error',e=>executionErrors.push(e.message));addEventListener('unhandledrejection',e=>executionErrors.push(String(e.reason)))")
            click('[data-stage-layout=video]');click('[data-detail=progress]')
            wait.until(lambda _:len(driver.find_elements('css selector','[data-execution-phase]'))==5)
            check('real candidate phases load without automatic approvals',report()['summary']['confirmed']==0)
            css=open_phase(2)
            js('arguments[0].open=true',el(css+' .execution-quant'))
            m=next(m for m in report()['phases'][2]['quantitative'] if m['key']=='tilt_p95_deg')
            check('quantified native tilt is displayed with its trial limit',f"{m['value']:.3f}" in el(css+' [data-execution-metric=tilt_p95_deg]').text and '10' in el(css+' [data-execution-metric=tilt_p95_deg]').text)
            check('unmeasured object drift never appears as passing','缺必要数据' in el(css+' [data-execution-metric=held_drift_peak_mm]').text)
            js('arguments[0].open=false',el(css))
            css=open_phase(4)
            check('retreat requires arm, whole robot, and safety',len(el(css).find_elements('css selector','[data-execution-check]'))==3)
            check('retreat has no unrequested speed criterion',not el(css).find_elements('css selector','[data-execution-target]'))
            choose(css+' [data-execution-check=arm_clear]','pass')
            choose(css+' [data-execution-check=base_clear]','unknown')
            choose(css+' [data-execution-check=safety]','unknown')
            fill(css+' [data-execution-note]','AUTOMATED UI FIXTURE in isolated database; not a real safety assessment.')
            save(css,1)
            check('arm withdrawal alone never approves retreat',report()['phases'][4]['state']=='unknown')
            css=open_phase(0)
            choose(css+' [data-execution-check=safety]','pass')
            fill(css+' [data-execution-start]','.5');fill(css+' [data-execution-end]','2.5')
            fill(css+' [data-execution-target]','1');fill(css+' [data-execution-basis]','Synthetic test threshold')
            fill(css+' [data-execution-note]','AUTOMATED UI FIXTURE: test duration recalculation only.')
            click(css+' [data-execution-boundary]');save(css,2)
            p=report()['phases'][0]
            check('corrected interval recomputes duration and flags exceeded target',p['duration_s']==2. and p['state']=='fail' and p['interval_source']=='human_corrected')
            fill(css+' [data-execution-target]','3');save(css,3)
            check('speed comparison updates after saving a supported target',report()['phases'][0]['state']=='passed')
            fill(css+' [data-execution-note]','Unsaved draft survives panel rerender')
            js("const x=document.querySelector('#stage-reason-filter');x.dispatchEvent(new Event('change',{bubbles:true}))")
            check('unsaved audit draft survives model reason filtering',el(css+' [data-execution-note]').get_attribute('value')=='Unsaved draft survives panel rerender')
            driver.refresh();wait.until(lambda _:driver.find_elements('css selector','[data-detail=progress]'));click('[data-detail=progress]')
            wait.until(lambda _:driver.find_elements('css selector','[data-execution-phase]'))
            click('[data-stage-layout=video]')
            css=open_phase(4)
            check('saved independent review survives reload',el(css+' [data-execution-check=base_clear]').get_attribute('value')=='unknown')
            for width,height,name in [(1580,1050,'desktop'),(850,1100,'tablet'),(390,844,'phone')]:
                driver.set_window_size(width,height)
                js("document.querySelector('.execution-quality').scrollIntoView({block:'start'})")
                check(name+' has no page horizontal overflow',not js('return document.documentElement.scrollWidth>innerWidth'))
                driver.save_screenshot(str(out/(name+'.png')))
            driver.set_window_size(1580,1050)
            css=open_phase(2);js('arguments[0].open=true',el(css+' .execution-quant'))
            js("arguments[0].scrollIntoView({block:'start'})",el(css+' .execution-quant'))
            driver.save_screenshot(str(out/'quantitative.png'))
            check('browser has no runtime errors',js('return window.executionErrors||[]')==[])
            check('existing grades and clip reviews remain unchanged',lib.store.all()=={})
            check('raw MCAP remains unchanged',(source.stat().st_size,source.stat().st_mtime_ns)==source_before)
            check('stage predictions remain unchanged',lib.progress_service.current(EP,MODEL)==original)
            (out/'report.json').write_text(json.dumps(dict(passed=True,checks=checks,source='Real recording, existing model output; all human decisions synthetic and isolated.'),ensure_ascii=False,indent=2)+'\n')
        except Exception:
            driver.save_screenshot(str(out/'failure.png'));raise
        finally:
            driver.quit();http.shutdown();http.server_close();thread.join()
            lib.progress_service.close();lib.pool.shutdown();lib.export_pool.shutdown()


if __name__=='__main__':main()
