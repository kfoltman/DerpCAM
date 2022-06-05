from PyQt5.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

class ExpectError(object):
    def __init__(self, test, expectedMsg):
        self.test = test
        self.passed = False
        self.expectedMsg = expectedMsg
    def critical(self, parent, title, msg):
        if msg == self.expectedMsg:
            self.passed = True
        else:
            self.test.assertEqual(msg, self.expectedMsg)
    def __enter__(self):
        self.old_critical = QMessageBox.critical
        QMessageBox.critical = lambda parent, title, msg: self.critical(parent, title, msg)
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.test.assertTrue(self.passed, f"Expected exception not thrown: {self.expectedMsg}")
        QMessageBox.critical = self.old_critical

class ExpectNoError(object):
    def __init__(self, test):
        self.test = test
        self.passed = True
    def critical(self, parent, title, msg):
        self.test.assertTrue(False, msg)
    def __enter__(self):
        self.old_critical = QMessageBox.critical
        QMessageBox.critical = lambda parent, title, msg: self.critical(parent, title, msg)
    def __exit__(self, exc_type, exc_value, exc_traceback):
        QMessageBox.critical = self.old_critical

class ExpectQuestion(object):
    def __init__(self, test, snippet, answer):
        self.test = test
        self.passed = False
        self.answer = answer
        self.snippet = snippet
    def question(self, parent, title, msg):
        if self.snippet in msg:
            self.passed = True
        else:
            self.test.assertIn(self.snippet, msg)
        return self.answer
    def __enter__(self):
        self.old_question = QMessageBox.question
        QMessageBox.question = lambda parent, title, msg: self.question(parent, title, msg)
    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.test.assertTrue(self.passed, f"Expected question not asked: {self.snippet}")
        QMessageBox.question = self.question

