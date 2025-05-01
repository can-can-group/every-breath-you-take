import sys
import time
import asyncio
import logging

import numpy as np
import neurokit2 as nk  # only needed if you have a raw ECG waveform

from PySide6.QtCore import QTimer, Qt, QPointF, Slot, QSize, QMargins, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QWidget, QComboBox, QPushButton, QGraphicsDropShadowEffect,
    QMainWindow, QGridLayout
)
from PySide6.QtCharts import QChartView, QLineSeries, QScatterSeries, QAreaSeries
from PySide6.QtGui import QPen, QPainter, QColor, QFont, QBrush, QIcon, QPainterPath, QMovie

from Model import Model
from sensor import SensorHandler
from views.widgets import CirclesWidget, SquareWidget
from views.charts import (
    create_chart, create_scatter_series,
    create_line_series, create_spline_series,
    create_axis
)
from styles.colours import RED, YELLOW, GREEN, BLUE, GRAY, GOLD, PURPLE, DARK_BG, CHART_BG, TEXT_COLOR, LINEWIDTH, DOTSIZE_SMALL
from styles.utils import get_stylesheet

# Add a HeartWidget for pulsing heart animation
class HeartWidget(QWidget):
    """A widget that displays a pulsing heart animation using a GIF."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 150)
        
        # Load the GIF animation from file
        self.movie = QMovie("img/heartbeat-animation.gif")
        self.movie.setScaledSize(QSize(150, 150))  # Scale to widget size
        
        # Start the animation
        self.movie.start()
        
        # Connect frameChanged signal to update the widget
        self.movie.frameChanged.connect(self.update)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw the current frame of the GIF
        current_frame = self.movie.currentPixmap()
        painter.drawPixmap(self.rect(), current_frame)
        
        painter.end()

class View(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.model = Model()

        # connect sensor signals
        self.model.sensor_connected.connect(self._on_sensor_connected)
        self.sensor_handler = SensorHandler()
        self.sensor_handler.scan_complete.connect(self._on_scan_complete)

        # Apply dark mode
        self.setStyleSheet(get_stylesheet("styles/style.qss"))
        
        # Set widget background
        main_widget = QWidget()
        main_widget.setStyleSheet(f"background-color: {DARK_BG.name()};")
        self.setCentralWidget(main_widget)

        # update intervals (ms)
        self.UPDATE_SERIES_PERIOD = 100
        self.UPDATE_BREATHING_SERIES_PERIOD = 50
        self.UPDATE_PACER_PERIOD = 10

        # history parameters
        self.PACER_HIST_SIZE = 6000
        self.BREATH_ACC_TIME_RANGE = 60
        self.HRV_SERIES_TIME_RANGE = 300

        # initial pacer rate
        self.pacer_rate = 6

        # Set minimum window size to ensure charts remain visible
        self.setMinimumWidth(800)
        self.setMinimumHeight(600)
        
        # Track window state
        self.compact_mode = False
        
        # Register window resizing handler
        self.resizeEvent = self.handleResize

        # build and arrange charts
        self.create_breath_chart()
        self.create_hrv_chart()
        self.create_circles_layout()
        self.create_bpm_chart()
        self.set_view_layout()
        self.start_view_update()

        # pacer buffers
        self.pacer_values_hist = np.full((self.PACER_HIST_SIZE, 1), np.nan)
        self.pacer_times_hist = np.full((self.PACER_HIST_SIZE, 1), np.nan)
        self.pacer_times_hist_rel_s = np.full(self.PACER_HIST_SIZE, np.nan)

    def create_breath_chart(self):
        """Breathing acceleration + HR chart."""
        self.chart_breath = create_chart(showTitle=False, showLegend=False)
        self.series_pacer = create_line_series(GOLD, LINEWIDTH)
        self.series_breath_acc = create_line_series(BLUE, LINEWIDTH)
        self.series_breath_cycle = create_scatter_series(GRAY, DOTSIZE_SMALL)
        self.series_hr = create_scatter_series(RED, DOTSIZE_SMALL)

        self.axis_breath_x = create_axis(
            None, tickCount=10,
            rangeMin=-self.BREATH_ACC_TIME_RANGE, rangeMax=0,
            labelSize=16, flip=False
        )
        self.axis_breath_y = create_axis(
            "Chest acc (m/s²)", BLUE,
            rangeMin=-1, rangeMax=1, labelSize=16
        )
        self.axis_hr_y = create_axis(
            "HR (bpm)", RED,
            rangeMin=40, rangeMax=200, labelSize=16
        )

        for s in (self.series_pacer, self.series_breath_acc,
                  self.series_breath_cycle, self.series_hr):
            self.chart_breath.addSeries(s)
        self.chart_breath.addAxis(self.axis_breath_x, Qt.AlignBottom)
        self.chart_breath.addAxis(self.axis_breath_y, Qt.AlignRight)
        self.chart_breath.addAxis(self.axis_hr_y, Qt.AlignLeft)

        self.series_pacer.attachAxis(self.axis_breath_x)
        self.series_pacer.attachAxis(self.axis_breath_y)
        self.series_breath_acc.attachAxis(self.axis_breath_x)
        self.series_breath_acc.attachAxis(self.axis_breath_y)
        self.series_breath_cycle.attachAxis(self.axis_breath_x)
        self.series_breath_cycle.attachAxis(self.axis_breath_y)
        self.series_hr.attachAxis(self.axis_breath_x)
        self.series_hr.attachAxis(self.axis_hr_y)

    def create_hrv_chart(self):
        """Heart rate variability chart."""
        self.chart_hrv = create_chart(showTitle=False, showLegend=False)

        # breathing rate
        self.series_br = create_spline_series(BLUE, LINEWIDTH)
        self.series_br_marker = create_scatter_series(GRAY, DOTSIZE_SMALL)
        self.series_br_marker.setMarkerShape(QScatterSeries.MarkerShapeTriangle)
        self.axis_br_y = create_axis(
            "BR (bpm)", BLUE, rangeMin=0, rangeMax=20, labelSize=16
        )

        # RMSSD / max-min
        self.series_maxmin = create_spline_series(RED, LINEWIDTH)
        self.series_maxmin_marker = create_scatter_series(RED, DOTSIZE_SMALL)
        self.axis_hrv_x = create_axis(
            None, tickCount=10,
            rangeMin=-self.HRV_SERIES_TIME_RANGE, rangeMax=0, labelSize=16
        )
        self.axis_hrv_y = create_axis(
            "HRV (ms)", RED, rangeMin=0, rangeMax=250, labelSize=16
        )

        # HRV bands (store to avoid GC)
        self.hrv_bands = []
        for low, high, col in ((0,50,RED),(50,150,YELLOW),(150,2000,GREEN)):
            low_line = QLineSeries()
            low_line.append(-self.HRV_SERIES_TIME_RANGE, low)
            low_line.append(0, low)
            high_line = QLineSeries()
            high_line.append(-self.HRV_SERIES_TIME_RANGE, high)
            high_line.append(0, high)
            band = QAreaSeries(low_line, high_line)
            band.setColor(col)
            band.setOpacity(0.2)
            band.setPen(QPen(Qt.NoPen))
            self.hrv_bands.append((low_line, high_line, band))
            self.chart_hrv.addSeries(band)

        self.chart_hrv.addSeries(self.series_maxmin)
        self.chart_hrv.addSeries(self.series_maxmin_marker)
        self.chart_hrv.addSeries(self.series_br_marker)

        self.chart_hrv.addAxis(self.axis_hrv_x, Qt.AlignBottom)
        self.chart_hrv.addAxis(self.axis_hrv_y, Qt.AlignLeft)
        self.chart_hrv.addAxis(self.axis_br_y, Qt.AlignRight)

        self.series_maxmin.attachAxis(self.axis_hrv_x)
        self.series_maxmin.attachAxis(self.axis_hrv_y)
        self.series_maxmin_marker.attachAxis(self.axis_hrv_x)
        self.series_maxmin_marker.attachAxis(self.axis_hrv_y)
        self.series_br_marker.attachAxis(self.axis_hrv_x)
        self.series_br_marker.attachAxis(self.axis_br_y)

    def create_bpm_chart(self):
        """Live BPM chart."""
        self.chart_bpm = create_chart(title="Heart Rate", showTitle=True)
        
        # Set the title font to be larger
        title_font = QFont("Arial", 21, QFont.Bold)  # Increased title font size
        self.chart_bpm.setTitleFont(title_font)
        
        self.series_bpm = create_line_series(PURPLE, LINEWIDTH)
        self.axis_bpm_x = create_axis(
            None, tickCount=10,
            rangeMin=-self.HRV_SERIES_TIME_RANGE, rangeMax=0, labelSize=16
        )
        self.axis_bpm_y = create_axis(
            "BPM", PURPLE, rangeMin=40, rangeMax=200, labelSize=16
        )

        self.chart_bpm.addSeries(self.series_bpm)
        self.chart_bpm.addAxis(self.axis_bpm_x, Qt.AlignBottom)
        self.chart_bpm.addAxis(self.axis_bpm_y, Qt.AlignLeft)
        self.series_bpm.attachAxis(self.axis_bpm_x)
        self.series_bpm.attachAxis(self.axis_bpm_y)

        self.bpm_view = QChartView(self.chart_bpm)
        self.bpm_view.setRenderHint(QPainter.Antialiasing)
        self.bpm_view.setStyleSheet("background-color: transparent;")

        # Create container for BPM text display and heart animation
        self.bpm_header = QWidget()
        bpm_header_layout = QHBoxLayout(self.bpm_header)
        bpm_header_layout.setContentsMargins(5, 15, 5, 5)  # Add top padding
        bpm_header_layout.setSpacing(10)
        
        # Large BPM text display
        self.bpm_text = QLabel("-- BPM")
        self.bpm_text.setFont(QFont("Arial", 28, QFont.Bold))  # Increased from 28 to 34
        self.bpm_text.setStyleSheet(f"color: {PURPLE.name()};")
        self.bpm_text.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        # Pulsing heart animation
        self.heart_widget = HeartWidget()
        
        # Add widgets to header layout
        bpm_header_layout.addWidget(self.heart_widget)
        bpm_header_layout.addWidget(self.bpm_text)
        bpm_header_layout.addStretch(1)
        
        # Create a container for both the header and the chart view
        self.bpm_container = QWidget()
        bpm_container_layout = QVBoxLayout(self.bpm_container)
        bpm_container_layout.setContentsMargins(0, 0, 0, 0)
        bpm_container_layout.setSpacing(0)
        
        # Add header to the top, then the chart below
        bpm_container_layout.addWidget(self.bpm_header)
        bpm_container_layout.addWidget(self.bpm_view)

    def update_bpm_series(self):
        pts = self.model.hrv_analyser.hr_history.get_qpoint_list()
        self.series_bpm.replace(pts)
        if pts:
            val = int(pts[-1].y())
            # Update the BPM text at the top of the chart
            self.bpm_text.setText(f"{val} BPM")

    def create_circles_layout(self):
        """Creates the breathing visualization and controls layout."""
        self.controlWidget = QWidget()
        self.controlWidget.setObjectName("controlWidget")
        self.controlWidget.setMinimumWidth(250)
        self.controlWidget.setMaximumWidth(300)
        
        # Add drop shadow to control widget for depth
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 80))
        shadow.setOffset(3, 3)
        self.controlWidget.setGraphicsEffect(shadow)

        # Create breathing circles widget with modern styling
        self.circles = CirclesWidget(
            x_values=self.model.pacer.cos_theta, 
            y_values=self.model.pacer.sin_theta,
            pacer_color=PURPLE,       # Use purple for pacer
            breathing_color=BLUE,     # Use blue for breathing
            hr_color=RED,             # Use red for heart rate
            background_image="img/lungs.png"  # Add the lungs background image
        )
        self.circles.setMinimumSize(200, 200)
        self.circles.setRenderHint(QPainter.Antialiasing)
        
        # Create a widget to hold the breathing visualization
        self.breathingVisualContainer = QWidget()
        self.breathingVisualContainer.setMinimumHeight(300)
        
        # Create a layout for the circles
        breathingLayout = QGridLayout(self.breathingVisualContainer)
        breathingLayout.setContentsMargins(0, 0, 0, 0)
        
        # Add circles to the layout
        breathingLayout.addWidget(self.circles, 0, 0, Qt.AlignCenter)
        
        # Style the rate slider for modern appearance
        self.rate_slider = QSlider(Qt.Horizontal)
        self.rate_slider.setMinimum(4)
        self.rate_slider.setMaximum(12)
        self.rate_slider.setValue(self.pacer_rate)
        self.rate_slider.setTickPosition(QSlider.TicksBelow)
        self.rate_slider.setTickInterval(1)
        self.rate_slider.valueChanged.connect(self.update_pacer_rate)
        
        # Modern styled rate label
        self.rate_label = QLabel(f"Breathing rate: {self.pacer_rate} bpm")
        self.rate_label.setFont(QFont("Arial", 21))  # Increased from 12 to 16
        self.rate_label.setAlignment(Qt.AlignCenter)
        
        # Add sensor controls section title
        sensorGroupLabel = QLabel("Sensor Connection")
        sensorGroupLabel.setFont(QFont("Arial", 21, QFont.Bold))
        sensorGroupLabel.setAlignment(Qt.AlignCenter)
        
        # Create enhanced buttons with icons
        self.scan_button = QPushButton("  Scan for Devices")
        self.scan_button.setFont(QFont("Arial", 11))
        self.scan_button.setIcon(QIcon("img/scan.png"))
        self.scan_button.setIconSize(QSize(24, 24))
        self.scan_button.setMinimumHeight(40)
        self.scan_button.setObjectName("actionButton")
        self.scan_button.setStyleSheet("""
            QPushButton#actionButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D23888, stop:1 #e76c9e);
                border-radius: 8px;
                padding: 8px 16px;
                color: white;
                text-align: left;
                border: none;
            }
            QPushButton#actionButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e358a2, stop:1 #f086b5);
            }
            QPushButton#actionButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b22a74, stop:1 #c75689);
            }
        """)
        self.scan_button.clicked.connect(self._on_scan_button_press)
        
        # Create device selection dropdown
        self.sensor_combo = QComboBox()
        self.sensor_combo.setFont(QFont("Arial", 11))
        self.sensor_combo.setMinimumHeight(40)
        self.sensor_combo.setStyleSheet("""
            QComboBox {
                border-radius: 8px;
                padding: 8px 16px;
                background-color: #2d2d2d;
                border: 1px solid #333333;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: center right;
                width: 24px;
                border-left: 1px solid #333333;
                border-top-right-radius: 8px;
                border-bottom-right-radius: 8px;
            }
        """)
        
        # Connect button styling
        self.connect_button = QPushButton("  Connect")
        self.connect_button.setFont(QFont("Arial", 11))
        self.connect_button.setIcon(QIcon("img/connect.png"))
        self.connect_button.setIconSize(QSize(24, 24))
        self.connect_button.setMinimumHeight(40) 
        self.connect_button.setObjectName("actionButton")
        self.connect_button.setStyleSheet("""
            QPushButton#actionButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #D23888, stop:1 #e76c9e);
                border-radius: 8px;
                padding: 8px 16px;
                color: white;
                text-align: left;
                border: none;
            }
            QPushButton#actionButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e358a2, stop:1 #f086b5);
            }
            QPushButton#actionButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #b22a74, stop:1 #c75689);
            }
            QPushButton#actionButton:disabled {
                background: #444444;
                color: #888888;
            }
        """)
        self.connect_button.clicked.connect(self._on_connect_button_press)
        self.connect_button.setEnabled(False)
        
        # Layout setup with proper spacing for a modern look
        controlLayout = QVBoxLayout()
        controlLayout.setContentsMargins(15, 15, 15, 15)
        controlLayout.setSpacing(15)
        
        # Add title label for the control panel
        title_label = QLabel("Breathing Control")
        title_label.setFont(QFont("Arial", 21, QFont.Bold))  # Increased from 14 to 18
        title_label.setAlignment(Qt.AlignCenter)
        controlLayout.addWidget(title_label)
        
        # Add circles widget
        circleContainer = QWidget()
        circleContainer.setMinimumHeight(300) # Ensure enough space
        circleLayout = QVBoxLayout(circleContainer)
        circleLayout.setContentsMargins(0, 10, 0, 10)
        circleLayout.setAlignment(Qt.AlignCenter) # Center alignment for the layout
        circleLayout.addWidget(self.breathingVisualContainer, 0, Qt.AlignCenter)
        self.circles.setMinimumSize(240, 240)  # Increase size for better visibility
        controlLayout.addWidget(circleContainer, 0, Qt.AlignCenter) # Center the container in parent layout
        
        # Add rate control
        controlLayout.addWidget(self.rate_label)
        controlLayout.addWidget(self.rate_slider)
        
        # Add spacer before sensor controls
        controlLayout.addSpacing(10)
        
        # Add sensor controls section
        controlLayout.addWidget(sensorGroupLabel)
        
        # Add connection details indicator
        self.connection_status = QLabel("Not Connected")
        self.connection_status.setFont(QFont("Arial", 18))
        self.connection_status.setAlignment(Qt.AlignCenter)
        self.connection_status.setStyleSheet("color: #ef4444;")
        controlLayout.addWidget(self.connection_status)
        
        # Sensor controls layout
        controlLayout.addWidget(self.scan_button)
        controlLayout.addWidget(self.sensor_combo)
        controlLayout.addWidget(self.connect_button)
        
        # Add spacer at the bottom
        controlLayout.addStretch()
        
        self.controlWidget.setLayout(controlLayout)

    def set_view_layout(self):
        """
        Layout structure:
        - Top section:
            - Control panel (left)
            - Heart Rate (right)
        - Bottom section:
            - Breath (left)
            - HRV (right)
        """
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        self.centralWidget().setLayout(main_layout)

        # Top section: Control panel (left) and Heart Rate (right)
        topSectionWidget = QWidget()
        topSectionLayout = QHBoxLayout(topSectionWidget)
        topSectionLayout.setContentsMargins(0, 0, 0, 0)
        topSectionLayout.setSpacing(10)

        # Left side of top section - Control Panel
        topSectionLayout.addWidget(self.controlWidget, 1)

        # Right side of top section - Heart Rate chart
        topSectionLayout.addWidget(self.bpm_container, 2)

        # Bottom section: Breath (left) and HRV (right) charts
        bottomSectionWidget = QWidget()
        bottomSectionLayout = QHBoxLayout(bottomSectionWidget)
        bottomSectionLayout.setContentsMargins(0, 0, 0, 0)
        bottomSectionLayout.setSpacing(10)

        # Create chart views if they don't exist
        if not hasattr(self, 'breathView'):
            self.breathView = QChartView(self.chart_breath)
            self.breathView.setRenderHint(QPainter.Antialiasing)
            self.breathView.setStyleSheet("background-color: transparent;")
            
        if not hasattr(self, 'hrvView'):
            self.hrvView = QChartView(self.chart_hrv)
            self.hrvView.setRenderHint(QPainter.Antialiasing)
            self.hrvView.setStyleSheet("background-color: transparent;")

        # Add Breath and HRV charts to bottom section
        bottomSectionLayout.addWidget(self.breathView, 1)
        bottomSectionLayout.addWidget(self.hrvView, 1)

        # Add the two main sections to the main layout
        main_layout.addWidget(topSectionWidget, 1)
        main_layout.addWidget(bottomSectionWidget, 1)
        
        # Make sure the circles background is updated
        QTimer.singleShot(100, self.update_circles_background)

    def start_view_update(self):
        self.update_series_timer = QTimer()
        self.update_series_timer.timeout.connect(self.update_series)
        self.update_series_timer.start(self.UPDATE_SERIES_PERIOD)

        self.update_acc_timer = QTimer()
        self.update_acc_timer.timeout.connect(self.update_acc_series)
        self.update_acc_timer.start(self.UPDATE_BREATHING_SERIES_PERIOD)

        self.pacer_timer = QTimer()
        self.pacer_timer.timeout.connect(self.plot_circles)
        self.pacer_timer.start(self.UPDATE_PACER_PERIOD)

        self.bpm_timer = QTimer()
        self.bpm_timer.timeout.connect(self.update_bpm_series)
        self.bpm_timer.start(self.UPDATE_SERIES_PERIOD)

    def update_pacer_rate(self):
        self.pacer_rate = self.rate_slider.value()
        self.rate_label.setText(f"Breathing rate: {self.pacer_rate} bpm")

    def plot_circles(self):
        coords = self.model.pacer.update(self.pacer_rate)
        self.circles.update_pacer_series(*coords)

        self.pacer_values_hist = np.roll(self.pacer_values_hist, -1)
        self.pacer_values_hist[-1] = np.linalg.norm([coords[0][0], coords[1][0]]) - 0.5
        self.pacer_times_hist = np.roll(self.pacer_times_hist, -1)
        self.pacer_times_hist[-1] = time.time_ns() / 1e9

        breath_coords = self.model.breath_analyser.get_breath_circle_coords()
        self.circles.update_breath_series(*breath_coords)

    def update_acc_series(self):
        self.pacer_times_hist_rel_s = self.pacer_times_hist - time.time_ns() / 1e9

        acc_pts = self.model.breath_analyser.chest_acc_history.get_qpoint_list()
        self.series_breath_acc.replace(acc_pts)
        cyc_pts = self.model.breath_analyser.chest_acc_history.get_qpoint_marker_list()
        self.series_breath_cycle.replace(cyc_pts)

        pacer_pts = [
            QPointF(t, v)
            for t, v in zip(
                self.pacer_times_hist_rel_s.flatten(),
                self.pacer_values_hist.flatten()
            )
            if not np.isnan(t)
        ]
        if pacer_pts:
            self.series_pacer.replace(pacer_pts)

    def update_series(self):
        hr_pts = self.model.hrv_analyser.hr_history.get_qpoint_list()
        self.series_hr.replace(hr_pts)

        br_pts = self.model.breath_analyser.br_history.get_qpoint_list()
        self.series_br.replace(br_pts)
        self.series_br_marker.replace(br_pts)

        mm_pts = self.model.hrv_analyser.maxmin_history.get_qpoint_list()
        self.series_maxmin.replace(mm_pts)
        self.series_maxmin_marker.replace(mm_pts)

    @Slot()
    def _on_scan_button_press(self):
        asyncio.create_task(self.sensor_handler.scan())

    @Slot()
    def _on_scan_complete(self):
        device_names = self.sensor_handler.get_valid_device_names()
        self.sensor_combo.clear()
        self.sensor_combo.addItems(device_names)
        self.connect_button.setEnabled(len(device_names) > 0)

    @Slot()
    def _on_connect_button_press(self):
        selected_device = self.sensor_combo.currentText()
        sensor = self.sensor_handler.create_sensor_client(selected_device)
        asyncio.create_task(self.set_sensor(sensor))

    async def set_sensor(self, sensor):
        try:
            await self.model.set_and_connect_sensor(sensor)
        except Exception as e:
            self.logger.error(f"Error: Failed to connect – {e}")
            sys.exit(1)

    async def main(self):
        await self.sensor_handler.scan()

    @Slot()
    def _on_sensor_connected(self):
        self.connection_status.setText("Connected")
        self.connection_status.setStyleSheet("color: #10b981;")

    def handleResize(self, event):
        """Handle window resize events to adjust layout as needed."""
        width = event.size().width()
        
        # Check if we should switch to compact mode (width < 1000px)
        new_compact_mode = width < 1000
        
        # Only update if the mode changed
        if new_compact_mode != self.compact_mode:
            self.compact_mode = new_compact_mode
            
            # Adjust control panel width based on window size
            if self.compact_mode:
                self.controlWidget.setMaximumWidth(220)
            else:
                self.controlWidget.setMaximumWidth(300)
            
            # Auto-adjust chart axes for better display in compact mode
            self._update_chart_for_compact_mode()
        
        # Pass event to parent class
        super().resizeEvent(event)
    
    def _update_chart_for_compact_mode(self):
        """Adjust chart properties for compact mode."""
        # Breathing chart
        if self.compact_mode:
            self.axis_breath_x.setTickCount(4)
            self.axis_breath_y.setTickCount(4)
            self.axis_hr_y.setTickCount(4)
        else:
            self.axis_breath_x.setTickCount(6)
            self.axis_breath_y.setTickCount(6)
            self.axis_hr_y.setTickCount(6)
        
        # HRV chart
        if self.compact_mode:
            self.axis_hrv_x.setTickCount(4)
            self.axis_hrv_y.setTickCount(4)
            self.axis_br_y.setTickCount(4)
        else:
            self.axis_hrv_x.setTickCount(6)
            self.axis_hrv_y.setTickCount(6)
            self.axis_br_y.setTickCount(6)
        
        # BPM chart
        if self.compact_mode:
            self.axis_bpm_x.setTickCount(4)
            self.axis_bpm_y.setTickCount(4)
        else:
            self.axis_bpm_x.setTickCount(6)
            self.axis_bpm_y.setTickCount(6)

    def update_circles_background(self):
        """Force update of the circles background image"""
        if hasattr(self, 'circles'):
            self.circles.apply_background_image_to_chart()