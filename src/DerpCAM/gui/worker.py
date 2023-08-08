import threading

class WorkerThread(threading.Thread):
    def __init__(self, parentOp, workerFunc, cam):
        self.worker_func = workerFunc
        self.parent_operation = parentOp
        self.cam = cam
        self.exception = None
        self.exception_text = None
        self.progress = (0, 10000000)
        self.cancelled = False
        threading.Thread.__init__(self, target=self.threadMain)
    def getProgress(self):
        return self.progress
    def cancel(self):
        self.cancelled = True
    def threadMain(self):
        try:
            self.worker_func()
            if self.cam and self.cam.is_nothing():
                self.parent_operation.addWarning("No cuts produced")
            self.progress = (self.progress[1], self.progress[1])
        except Exception as e:
            import traceback
            errorText = str(e)
            if not errorText:
                if isinstance(e, AssertionError):
                    errorText = traceback.format_exc(limit=1)
                else:
                    errorText = type(e).__name__
            self.exception = e
            self.exception_text = errorText
            if self.parent_operation and not self.parent_operation.error:
                self.parent_operation.error = errorText
            traceback.print_exc()

class WorkerThreadPack(object):
    def __init__(self, parentOp, threadDataList, parentCAM):
        self.parent_operation = parentOp
        self.parent_operation_cam = parentCAM
        self.threads = [WorkerThread(parentOp, workerFunc, cam) for cam, workerFunc in threadDataList]
        self.exception = None
        self.exception_text = None
    def getProgress(self):
        num = denom = 0
        for thread in self.threads:
            progress = thread.getProgress()
            num += progress[0]
            denom += progress[1]
        return (num, denom)
    def start(self):
        for thread in self.threads:
            thread.start()
    def cancel(self):
        for thread in self.threads:
            thread.cancel()
    def join(self):
        for thread in self.threads:
            thread.join()
            self.parent_operation_cam.add_all(thread.cam.operations)
        exceptions = ""
        for thread in self.threads:
            if thread.exception is not None:
                self.exception = thread.exception
                break
        for thread in self.threads:
            if thread.exception is not None:
                exceptions += thread.exception_text
        if exceptions:
            self.exception_text = exceptions
    def is_alive(self):
        return any([thread.is_alive() for thread in self.threads])
