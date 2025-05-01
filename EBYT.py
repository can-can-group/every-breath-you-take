import os
os.environ['QT_API'] = 'PySide6' # For qasync to know which binding is being used
os.environ['QT_LOGGING_RULES'] = 'qt.pointer.dispatch=false' # Disable pointer logging

import sys
import asyncio
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt
from qasync import QEventLoop
from View import View
import logging

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Enable dark mode styling at application level
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Use Fusion style for better dark mode support
    
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    # Create main application window
    main_window = View()
    main_window.setWindowTitle("Every Breath You Take")
    main_window.resize(1280, 720)  # Slightly larger starting size
    main_window.show()

    loop.create_task(main_window.main())
    loop.run_forever()
