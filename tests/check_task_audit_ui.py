"""Exercise the local task audit app with isolated headless Firefox."""
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait,Select

ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'workspace/evidence/task-audit';out.mkdir(parents=True,exist_ok=True)
options=Options();options.add_argument('-headless')
driver=webdriver.Firefox(options=options,service=Service('/snap/bin/geckodriver',service_args=['--profile-root',str(out)],log_output=str(out/'gecko.log')))
checks=[]
def check(label,value):
    assert value,label
    checks.append(label);print('PASS',label,flush=True)
def element(css):return driver.find_element('css selector',css)
try:
    driver.set_window_size(1460,1150)
    driver.get('http://127.0.0.1:8421/task-audit.html')
    wait=WebDriverWait(driver,30)
    driver.execute_script('document.querySelector("#task-score").closest("details").open=true')
    wait.until(lambda _:element('#task-score').text=='0.00')
    wait.until(lambda _:driver.execute_script('return document.querySelector("#frame").complete && document.querySelector("#frame").naturalWidth>0'))
    check('actual failed simulation changes from technical 10 to task 0',element('#technical').text=='10.00')
    wait.until(lambda _:'sim-chili-warp-v1' in element('#warp-note').text)
    check('WARP signed curve and task score are separate','成功率' in element('#warp-note').text)
    driver.execute_script('const s=document.querySelector("#seek");s.value=4;s.dispatchEvent(new Event("input"))')
    check('timeline seeks real local frames','4.0 /' in element('#time').text)
    driver.save_screenshot(str(out/'simulation-failure.png'))
    Select(element('#domain')).select_by_value('real')
    element('#search').send_keys('731492250911');element('.record').click()
    wait.until(lambda _:element('#task-score').text=='0.00')
    check('real automatic scores identify neural and measured-hand evidence','自动候选' in element('#result-state').text and '网络' in element('#score-source').text)
    wait.until(lambda _:len(driver.find_elements('css selector','#object-jumps button'))==6)
    element('#object-jumps button').click()
    wait.until(lambda _:len(driver.find_elements('css selector','#object-overlay rect'))>0)
    check('object boxes are attached to the actual evaluated frame',True)
    driver.execute_script('const s=document.querySelector("#seek");s.value=2;s.dispatchEvent(new Event("input"))')
    wait.until(lambda _:'旧检测框' in element('#object-note').text)
    check('unevaluated frames do not reuse stale object boxes',len(driver.find_elements('css selector','#object-overlay rect'))==0)
    element('#object-jumps button').click()
    driver.save_screenshot(str(out/'real-no-grasp.png'))
    element('#search').clear();Select(element('#domain')).select_by_value('control')
    element('.record').click();wait.until(lambda _:'任务标准待定义' in element('#result-state').text)
    check('different control task refuses transport score',element('#task-score').text=='—')
    wait.until(lambda _:'不匹配' in element('#warp-note').text or '不适用' in element('#warp-note').text)
    check('different control task refuses WARP transport inference',True)
    driver.set_window_size(760,1000)
    check('narrow view has no horizontal overflow',driver.execute_script('return document.documentElement.scrollWidth <= innerWidth'))
    driver.save_screenshot(str(out/'control-task-mobile.png'))
    (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
finally:driver.quit()
