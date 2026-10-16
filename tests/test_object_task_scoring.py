import copy
from object_task_scoring import visual_task_score,observation

def detection(label,box,score=.8):return dict(label=label,box=box,score=score)
def row(t,target,basket=None,hand=None,closed=0):
    boxes=[detection('green chili pepper',target)]
    if basket:boxes.append(detection('white basket',basket,.9))
    if hand:boxes.append(detection('robot hand',hand,.6))
    return dict(time_s=t,image_size=[1000,600],hand_closure=closed,detections=boxes)

def sequence():
    basket=[450,250,600,500]
    return [row(0,[700,300,740,340]),row(1,[720,300,760,340],basket,[710,290,820,450],.8)]+[row(t,[500,300,540,340],basket) for t in (2,3,4)]

def test_2d_release_candidate_is_never_certified_full_success():
    r=visual_task_score(sequence(),'chili_table_to_basket',True)
    assert r['score']==8
    assert r['completion'] is None
    assert r['evidence']['automatic_success_certified'] is False

def test_conflicting_failure_marker_requires_review():
    r=visual_task_score(sequence(),'chili_table_to_basket',False)
    assert r['score'] is None
    assert '冲突' in r['reason']

def test_repeated_single_frame_cannot_prove_settling():
    seq=sequence();seq[-2]['time_s']=seq[-1]['time_s'];seq[-3]['time_s']=seq[-1]['time_s']
    assert visual_task_score(seq,'chili_table_to_basket',True)['score'] is None

def test_inside_box_with_closed_hand_does_not_count_as_released():
    seq=sequence()
    for r in seq[-3:]:r['hand_closure']=.8
    assert visual_task_score(seq,'chili_table_to_basket',True)['score'] is None

def test_missing_target_does_not_mean_zero_or_completed():
    seq=sequence();seq[-1]['detections']=[d for d in seq[-1]['detections'] if d['label']=='white basket']
    assert visual_task_score(seq,'chili_table_to_basket',True)['score'] is None

def test_stationary_object_and_whole_hand_evidence_support_no_grasp():
    seq=[row(t,[700,300,740,340]) for t in range(6)]
    summary=dict(coverage=.99,max_closure=.65,closed_fraction=.03)
    assert visual_task_score(seq,'chili_table_to_basket',False,summary)['score']==0
    assert visual_task_score(seq,'chili_table_to_basket',False)['score'] is None

def test_other_tasks_are_rejected():
    assert visual_task_score(sequence(),'hand_control_test',True)['score'] is None

def test_empty_or_ambiguous_detection_is_not_certified():
    assert visual_task_score([],'chili_table_to_basket')['score'] is None
    r=row(0,[700,300,740,340]);r['detections'].append(detection('green chili pepper',[100,100,140,140],.79))
    assert observation(r)['ambiguous']

def test_object_mislabeled_as_hand_is_not_grasp_evidence():
    r=row(0,[700,300,740,340],hand=[700,300,740,340],closed=.8)
    assert not observation(r)['held_candidate']
