import sys
import time
import asyncio
import logging

import numpy as np
import neurokit2 as nk  # only needed if you have a raw ECG waveform

from PySide6.QtCore import QTimer, Qt, QPointF, Slot
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QWidget, QComboBox, QPushButton, QGraphicsDropShadowEffect
)
from PySide6.QtCharts import QChartView, QLineSeries, QScatterSeries, QAreaSeries
from PySide6.QtGui import QPen, QPainter, QColor, QFont

from Model import Model
from sensor import SensorHandler
from views.widgets import CirclesWidget, SquareWidget
from views.charts import (
    create_chart, create_scatter_series,
    create_line_series, create_spline_series,
    create_axis
)
from styles.colours import RED, YELLOW, GREEN, BLUE, GRAY, GOLD, LINEWIDTH, DOTSIZE_SMALL
from styles.utils import get_stylesheet


class View(QChartView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = logging.getLogger(__name__)
        self.model = Model()

        # connect sensor signals
        self.model.sensor_connected.connect(self._on_sensor_connected)
        self.sensor_handler = SensorHandler()
        self.sensor_handler.scan_complete.connect(self._on_scan_complete)

        # styling
        self.setStyleSheet(get_stylesheet("styles/style.qss"))

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

        # build and arrange charts
        self.create_breath_chart()
        self.create_hrv_chart()
        self.create_circles_layout()
        self.create_bpm_chart()
        self.create_ecg_chart()
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
            labelSize=10, flip=False
        )
        self.axis_breath_y = create_axis(
            "Chest acc (m/s²)", BLUE,
            rangeMin=-1, rangeMax=1, labelSize=10
        )
        self.axis_hr_y = create_axis(
            "HR (bpm)", RED,
            rangeMin=40, rangeMax=200, labelSize=10
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
            "BR (bpm)", BLUE, rangeMin=0, rangeMax=20, labelSize=10
        )

        # RMSSD / max-min
        self.series_maxmin = create_spline_series(RED, LINEWIDTH)
        self.series_maxmin_marker = create_scatter_series(RED, DOTSIZE_SMALL)
        self.axis_hrv_x = create_axis(
            None, tickCount=10,
            rangeMin=-self.HRV_SERIES_TIME_RANGE, rangeMax=0, labelSize=10
        )
        self.axis_hrv_y = create_axis(
            "HRV (ms)", RED, rangeMin=0, rangeMax=250, labelSize=10
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
        self.series_bpm = create_line_series(RED, LINEWIDTH)
        self.axis_bpm_x = create_axis(
            None, tickCount=10,
            rangeMin=-self.HRV_SERIES_TIME_RANGE, rangeMax=0, labelSize=10
        )
        self.axis_bpm_y = create_axis(
            "BPM", RED, rangeMin=40, rangeMax=200, labelSize=10
        )

        self.chart_bpm.addSeries(self.series_bpm)
        self.chart_bpm.addAxis(self.axis_bpm_x, Qt.AlignBottom)
        self.chart_bpm.addAxis(self.axis_bpm_y, Qt.AlignLeft)
        self.series_bpm.attachAxis(self.axis_bpm_x)
        self.series_bpm.attachAxis(self.axis_bpm_y)

        self.bpm_view = QChartView(self.chart_bpm)
        self.bpm_view.setRenderHint(QPainter.Antialiasing)
        self.bpm_view.setStyleSheet("background-color: transparent;")

        self.bpm_label = self.chart_bpm.scene().addText("BPM: --")
        self.bpm_label.setFont(QFont("Segoe UI", 10))
        self.bpm_label.setDefaultTextColor(RED)
        self.bpm_label.setPos(10, 10)

    def update_bpm_series(self):
        pts = self.model.hrv_analyser.hr_history.get_qpoint_list()
        self.series_bpm.replace(pts)
        if pts:
            val = int(pts[-1].y())
            self.bpm_label.setPlainText(f"BPM: {val} bpm")

    def create_ecg_chart(self):
        """Plot raw ECG samples from ecg_history."""
        self.chart_ecg = create_chart(title="ECG", showTitle=True)
        self.series_ecg = create_line_series(BLUE, LINEWIDTH)
        self.axis_ecg_x = create_axis(
            None, tickCount=10,
            rangeMin=-10, rangeMax=0, labelSize=10
        )
        self.axis_ecg_y = create_axis(
            "mV", BLUE, rangeMin=-2000, rangeMax=2000, labelSize=10
        )

        self.chart_ecg.addSeries(self.series_ecg)
        self.chart_ecg.addAxis(self.axis_ecg_x, Qt.AlignBottom)
        self.chart_ecg.addAxis(self.axis_ecg_y, Qt.AlignLeft)
        self.series_ecg.attachAxis(self.axis_ecg_x)
        self.series_ecg.attachAxis(self.axis_ecg_y)

        self.ecg_view = QChartView(self.chart_ecg)
        self.ecg_view.setRenderHint(QPainter.Antialiasing)
        self.ecg_view.setStyleSheet("background-color: transparent;")

        self.ecg_label = self.chart_ecg.scene().addText("ECG")
        self.ecg_label.setFont(QFont("Segoe UI", 10))
        self.ecg_label.setDefaultTextColor(GRAY)
        self.ecg_label.setPos(10, 10)

    def update_ecg_series(self):
        pts = self.model.ecg_history.get_qpoint_list()
        self.series_ecg.replace(pts)
        if not pts:
            return

        # auto-scale X axis
        xs = [p.x() for p in pts]
        self.axis_ecg_x.setRange(min(xs), max(xs))

        # auto-scale Y axis
        ys = [p.y() for p in pts]
        y_min, y_max = min(ys), max(ys)
        margin = 0.1 * (y_max - y_min or 1)
        self.axis_ecg_y.setRange(y_min - margin, y_max + margin)

        # — NeuroKit2 processing (uncomment if you have a true ECG waveform) —
        # values = np.array(ys)
        # clean = nk.ecg_clean(values, sampling_rate=250)
        # peaks, info = nk.ecg_peaks(clean, sampling_rate=250)
        # peak_ids = np.where(peaks["ECG_R_Peaks"])[0]
        # pts_r = [QPointF(xs[i], clean[i]) for i in peak_ids]
        # self.series_r_peaks.replace(pts_r)

    def create_circles_layout(self):
        self.circles_widget = CirclesWidget(
            *self.model.pacer.update(self.pacer_rate), GOLD, BLUE, RED
        )
        self.circles_widget.setRenderHint(QPainter.Antialiasing)

        self.pacer_slider = QSlider(Qt.Horizontal)
        self.pacer_slider.setRange(6, 20)
        self.pacer_slider.setValue(self.pacer_rate * 2)
        self.pacer_slider.valueChanged.connect(self.update_pacer_rate)

        self.pacer_label = QLabel(f"{self.pacer_rate}")
        self.pacer_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.pacer_label.setStyleSheet("color: black")
        self.pacer_label.setFixedWidth(40)

        slider_layout = QHBoxLayout()
        slider_layout.addWidget(self.pacer_label)
        slider_layout.addWidget(self.pacer_slider)
        slider_layout.addSpacing(20)

        layout = QVBoxLayout()
        layout.addWidget(self.circles_widget, alignment=Qt.AlignCenter)
        layout.addLayout(slider_layout)

        self.circles_layout = SquareWidget()
        self.circles_layout.setLayout(layout)

    def set_view_layout(self):
        main_layout = QVBoxLayout()
        graph_layout = QVBoxLayout()

        acc_v = QChartView(self.chart_breath)
        acc_v.setRenderHint(QPainter.Antialiasing)
        acc_v.setStyleSheet("background-color: transparent;")
        hrv_v = QChartView(self.chart_hrv)
        hrv_v.setRenderHint(QPainter.Antialiasing)
        hrv_v.setStyleSheet("background-color: transparent;")

        top_row = QHBoxLayout()
        top_row.addWidget(self.circles_layout, stretch=1)
        top_row.addWidget(acc_v, stretch=3)

        graph_layout.addLayout(top_row, stretch=1)
        graph_layout.addWidget(hrv_v, stretch=1)
        graph_layout.addWidget(self.bpm_view, stretch=1)
        graph_layout.addWidget(self.ecg_view, stretch=1)
        graph_layout.setContentsMargins(0,0,0,0)

        self.message_box = QLabel("Scanning...")
        self.message_box.setFixedSize(150,15)
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self._on_scan_button_press)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(10)
        shadow.setOffset(20,20)
        shadow.setColor(QColor(255,255,255,255))
        self.scan_button.setGraphicsEffect(shadow)

        self.device_menu = QComboBox()
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._on_connect_button_press)

        ctrl = QHBoxLayout()
        ctrl.addStretch(1)
        ctrl.addWidget(self.message_box)
        ctrl.addWidget(self.scan_button)
        ctrl.addWidget(self.device_menu)
        ctrl.addWidget(self.connect_button)
        ctrl.addStretch(1)

        ctrl_widget = QWidget()
        ctrl_widget.setObjectName("controlWidget")
        ctrl_widget.setLayout(ctrl)

        main_layout.addLayout(graph_layout, stretch=10)
        main_layout.addWidget(ctrl_widget, stretch=1)
        self.setLayout(main_layout)

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

        self.ecg_timer = QTimer()
        self.ecg_timer.timeout.connect(self.update_ecg_series)
        self.ecg_timer.start(self.UPDATE_SERIES_PERIOD)

    def update_pacer_rate(self):
        self.pacer_rate = self.pacer_slider.value() / 2
        self.pacer_label.setText(f"{self.pacer_rate}")

    def plot_circles(self):
        coords = self.model.pacer.update(self.pacer_rate)
        self.circles_widget.update_pacer_series(*coords)

        self.pacer_values_hist = np.roll(self.pacer_values_hist, -1)
        self.pacer_values_hist[-1] = np.linalg.norm([coords[0][0], coords[1][0]]) - 0.5
        self.pacer_times_hist = np.roll(self.pacer_times_hist, -1)
        self.pacer_times_hist[-1] = time.time_ns() / 1e9

        breath_coords = self.model.breath_analyser.get_breath_circle_coords()
        self.circles_widget.update_breath_series(*breath_coords)

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
        self.message_box.setText("Scanning...")
        asyncio.create_task(self.sensor_handler.scan())

    @Slot()
    def _on_scan_complete(self):
        self.message_box.setText("Select a sensor")
        self.device_menu.clear()
        self.device_menu.addItems(self.sensor_handler.get_valid_device_names())

    @Slot()
    def _on_connect_button_press(self):
        self.message_box.setText("Connecting...")
        name = self.device_menu.currentText()
        if name:
            sensor = self.sensor_handler.create_sensor_client(name)
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
        self.message_box.setText("Connected")