import copy
import pytest
from taskflow.evaluation import evaluate


def examples():
    segs=[dict(stage_id='place',start_s=0,end_s=2,completion='not_completed'),dict(stage_id='place',start_s=2,end_s=4,completion='completed')]
    labels=dict(annotation_status='human_confirmed',reviewer='synthetic test fixture',source_fingerprint='fixture',template_id='fixture',template_revision=1,evaluation_range=dict(start_s=0,end_s=4),segments=segs)
    run=dict(template_id='fixture',template_revision=1,result=dict(source_fingerprint='fixture',segments=copy.deepcopy(segs),analysis_range=dict(start_s=0,end_s=4)))
    return run,labels


def test_unconfirmed_or_wrong_source_cannot_produce_accuracy():
    run,labels=examples();labels['annotation_status']='vlm_proposal'
    with pytest.raises(ValueError,match='人工'):evaluate(run,labels)
    labels['annotation_status']='human_confirmed';labels['source_fingerprint']='other'
    with pytest.raises(ValueError,match='数据源'):evaluate(run,labels)


def test_human_overrides_are_not_used_to_make_model_accuracy_look_better():
    run,labels=examples();run['result']['segments'][0]['completion']='completed'
    run['result']['segments'][0]['effective_completion']='not_completed'
    result=evaluate(run,labels)
    assert result['failure_as_completed_rate']==1 and result['failure_detection_recall']==0


def test_merged_attempts_cannot_match_multiple_ground_truth_attempts():
    run,labels=examples();run['result']['segments']=[dict(stage_id='place',start_s=0,end_s=4,completion='completed')]
    result=evaluate(run,labels)
    assert result['matched_segments']==1 and result['segment_recall_at_iou_025']==.5
    assert result['failure_as_completed_rate']==1


def test_no_failure_examples_yields_no_failure_rate_not_zero():
    run,labels=examples()
    for seg in labels['segments']:seg['completion']='completed'
    assert evaluate(run,labels)['failure_as_completed_rate'] is None
