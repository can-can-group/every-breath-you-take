import time
import numpy as np
import logging

from Pacer import Pacer
from blehrm.interface import BlehrmClientInterface
from PySide6.QtCore import QObject, Signal
from analysis.HrvAnalyser import HrvAnalyser
from analysis.BreathAnalyser import BreathAnalyser
from analysis.HistoryBuffer import HistoryBuffer

class Model(QObject):
    """
    Core application model managing sensor connection, data streams,
    and analysis (HRV, breathing, raw ECG).
    """
    sensor_connected = Signal()

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.sensor_client = None
        self.pacer = Pacer()

        # Analysis modules
        self.hrv_analyser = HrvAnalyser()
        self.breath_analyser = BreathAnalyser()

        # Buffer for raw ECG samples (if available)
        self.ecg_history = HistoryBuffer(buffer_size=10000)

    async def set_and_connect_sensor(self, sensor: BlehrmClientInterface):
        """
        Connect to the sensor and start IBI, accelerometer, and ECG streams.
        """
        self.sensor_client = sensor
        await self.sensor_client.connect()
        await self.sensor_client.get_device_info()
        await self.sensor_client.print_device_info()

        # Start IBI (RR interval) stream
        await self.sensor_client.start_ibi_stream(callback=self.handle_ibi_callback)
        # Start accelerometer stream for breathing analysis
        await self.sensor_client.start_acc_stream(callback=self.handle_acc_callback)
        # Try to start raw ECG stream if supported
        try:
            await self.sensor_client.start_ecg_stream(callback=self.handle_ecg_callback)
        except Exception:
            self.logger.warning("ECG stream not available on this device")

        # Notify UI that sensor is connected
        self.sensor_connected.emit()

    async def disconnect_sensor(self):
        """
        Disconnect from the sensor.
        """
        if self.sensor_client:
            await self.sensor_client.disconnect()

    def handle_ibi_callback(self, data):
        """
        Callback for inter-beat interval (IBI) data.
        Updates the HRV analyser.
        """
        t, ibi = data
        self.hrv_analyser.update(t, ibi)

    def handle_acc_callback(self, data):
        """
        Callback for accelerometer data.
        Updates breathing analyser; on full breath, updates HRV metrics.
        """
        t = data[0]
        acc = data[1:]
        self.breath_analyser.update_chest_acc(t, acc)
        if self.breath_analyser.is_end_of_breath and not self.breath_analyser.br_history.is_empty():
            t_range = self.breath_analyser.get_last_breath_t_range()
            self.hrv_analyser.update_breath_by_breath_metrics(t_range)

    def handle_ecg_callback(self, data: bytes):
        """
        Callback for raw ECG bytes (int16 samples).
        Decodes and buffers them.
        """
        # Interpret as little-endian 16-bit integers
        samples = np.frombuffer(data, dtype=np.int16)
        # Timestamp of first sample
        t0 = time.time()
        # Assume a fixed ECG sampling rate (e.g., 250 Hz)
        dt = 1.0 / 250.0
        for i, val in enumerate(samples):
            timestamp = t0 + i * dt
            self.ecg_history.update(timestamp, float(val))
