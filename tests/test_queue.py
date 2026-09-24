import time
from videoremix.core.presets import PresetMode
from videoremix.queue.manager import BatchQueueManager
from videoremix.queue.task import TaskStatus

def test_batch_queue_execution(sample_video, tmp_path):
    qm = BatchQueueManager(max_workers=2)
    t1 = qm.add_task(sample_video, str(tmp_path / "q_test1.mp4"), PresetMode.QUALITY_FIRST)
    t2 = qm.add_task(sample_video, str(tmp_path / "q_test2.mp4"), PresetMode.BALANCED_REMIX)

    finished = False
    def done():
        nonlocal finished
        finished = True

    qm.on_queue_finished = done
    qm.start()

    for _ in range(30):
        if finished:
            break
        time.sleep(0.3)

    assert t1.status == TaskStatus.SUCCESS
    assert t2.status == TaskStatus.SUCCESS

def test_batch_queue_cancellation(sample_video, tmp_path):
    qm = BatchQueueManager(max_workers=1)
    t1 = qm.add_task(sample_video, str(tmp_path / "q_canc.mp4"), PresetMode.QUALITY_FIRST)
    qm.stop_all()
    assert t1.status == TaskStatus.CANCELLED
