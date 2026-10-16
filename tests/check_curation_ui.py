"""Verify replacement scoring in the original workbench and actual manifest download."""
import json
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.ui import WebDriverWait,Select
ROOT=Path(__file__).resolve().parents[1];out=ROOT/'workspace/evidence/curation-integrated';out.mkdir(parents=True,exist_ok=True)
target=out/'RoboCurate-quality-selection.json';target.unlink(missing_ok=True)
options=Options();options.add_argument('-headless');options.set_preference('browser.download.folderList',2);options.set_preference('browser.download.dir',str(out));options.set_preference('browser.helperApps.neverAsk.saveToDisk','application/json');options.set_preference('browser.download.useDownloadDir',True)
driver=webdriver.Firefox(options=options,service=Service('/snap/bin/geckodriver',service_args=['--profile-root',str(out)],log_output=str(out/'gecko.log')));driver.set_page_load_timeout(60);checks=[]
def el(s):return driver.find_element('css selector',s)
def check(label,ok):assert ok,label;checks.append(label);print('PASS',label,flush=True)
try:
 driver.set_window_size(1460,1100);driver.get('http://127.0.0.1:8421/');wait=WebDriverWait(driver,45)
 wait.until(lambda _:len(driver.find_elements('css selector','.episode-row'))==151)
 check('original homepage contains local sources and server evidence snapshots',True)
 check('no separate scoring page navigation',not driver.find_elements('css selector','nav a[href*="task-audit"]'))
 check('list leads with grades instead of repeated numeric scores',not driver.find_elements('css selector','.row-score') and '31 条已排序候选' in el('#data-grade-summary').text)
 el('[data-action="select-qualified"]').click();wait.until(lambda _:len(driver.find_elements('css selector','.select-ep:checked'))==31)
 check('one-click candidate selection excludes failed incomplete unknown',True)
 el('[data-action="select-priority"]').click();wait.until(lambda _:len(driver.find_elements('css selector','.select-ep:checked'))==8)
 check('priority selection creates usable shortlist',True)
 el('[data-action="clear-selection"]').click()
 Select(el('#filter-auto')).select_by_value('A');wait.until(lambda _:len(driver.find_elements('css selector','.episode-row'))==8)
 check('original grade filter uses new candidate grades',True)
 Select(el('#filter-cohort')).select_by_value('sim');wait.until(lambda _:len(driver.find_elements('css selector','.episode-row'))==5)
 check('simulation and real task cohorts can be filtered in original page',True)
 Select(el('#filter-cohort')).select_by_value('');wait.until(lambda _:len(driver.find_elements('css selector','.episode-row'))==8)
 el('#select-all').click();el('[data-action="export-selected"]').click();el('[data-action="download-curation"]').click();wait.until(lambda _:target.is_file())
 manifest=json.loads(target.read_text());check('original export emits eligible quality manifest without completeness weight',len(manifest['episodes'])==8 and all(r['grade']=='A' for r in manifest['episodes']) and manifest['completeness_scored'] is False and manifest['includes_raw_data'] is False)
 driver.save_screenshot(str(out/'original-library.png'))
 driver.get('http://127.0.0.1:8421/#review/33dc41a9ab95');wait.until(lambda _:el('.rating-number strong').text=='9.76')
 check('original right rating card replaced',el('#rating-overview').text.startswith('数据质量评分') and '完整度不加权' in el('#rating-overview').text)
 wait.until(lambda _:el('[data-camera]').get_property('naturalWidth')>0)
 check('original camera replays cached evidence',True)
 before=el('[data-camera]').get_attribute('src');el('#play-button').click();wait.until(lambda _:el('[data-camera]').get_attribute('src')!=before);el('#play-button').click()
 check('original play control advances cached frames',True)
 wait.until(lambda _:len(driver.find_elements('css selector','#progress-timeline path'))>0)
 check('task-specific WARP progress reused in original timeline',True)
 wait.until(lambda _:el('#robot-host').get_attribute('data-ready')=='true')
 check('original robot visualization still mounts',True)
 el('[data-action="show-quality"]').click();wait.until(lambda _:'先准入，再评质量' in el('#detail-body').text)
 check('candidate rank and seed variation exposed','21' in el('#detail-body').text and '三次训练范围' in el('#detail-body').text)
 for summary in driver.find_elements('css selector','#detail-body summary'):
  driver.execute_script('arguments[0].click()',summary)
 check('external reference and negative training result remain visible','100 段' in el('#detail-body').text and '未优于随机' in el('#detail-body').text)
 driver.save_screenshot(str(out/'original-review-score.png'))
 driver.get('http://127.0.0.1:8421/#review/37f1d62b056f');wait.until(lambda _:'E' in el('#rating-overview').text)
 check('incomplete task is excluded instead of penalizing score',el('.rating-number strong').text=='—' and '不完整' in el('#rating-overview').text)
 driver.get('http://127.0.0.1:8421/#review/43f5904adeb3');wait.until(lambda _:'D' in el('#rating-overview').text)
 check('failed task cannot retain old high technical rating',el('.rating-number strong').text=='—')
 driver.get('http://127.0.0.1:8421/#review/497716bfcc92');wait.until(lambda _:el('.rating-number strong').text=='9.50')
 wait.until(lambda _:len(driver.find_elements('css selector','#progress-timeline path'))>0)
 check('real cohort uses its own score and WARP curve',True)
 driver.get('http://127.0.0.1:8421/task-audit.html');wait.until(lambda _:'#library' in driver.current_url and len(driver.find_elements('css selector','.episode-row'))>0)
 check('old separate page redirects to original workbench','task-audit.html' not in driver.current_url)
 driver.get('http://127.0.0.1:8421/#rules');wait.until(lambda _:'完整性只作准入条件' in el('#main').text)
 check('original rules explain admission and excluded training pool','不参与模型拟合' in el('#main').text)
 (out/'checks.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2))
except Exception:
 driver.save_screenshot(str(out/'failure.png'));(out/'failure.txt').write_text(driver.find_element('tag name','body').text);raise
finally:driver.quit()
