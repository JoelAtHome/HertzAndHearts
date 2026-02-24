import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from hnh.view import View
from hnh.model import Model

class Application(QApplication):
    def __init__(self, sys_argv):
        super(Application, self).__init__(sys_argv)
        self._model = Model()
        self._view = View(self._model)
        
        # 1. The "Handshake" connection (Fast & Simple)
        self._view.sensor.ibi_update.connect(self._model.hr_handler)

        # 2. The "Math/Chart" connection (The Heavy Lifting)
        self._view.sensor.ibi_update.connect(self._model.update_ibis_buffer)
        
def main():
    app = Application(sys.argv)
    app._view.show()
    QTimer.singleShot(0, app._view.showMaximized)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()