from PySide6.QtCore import Qt, QMargins, QSize
from PySide6.QtWidgets import QSizePolicy, QWidget, QGraphicsDropShadowEffect
from PySide6.QtCharts import QChart, QChartView, QValueAxis, QSplineSeries, QAreaSeries
from PySide6.QtGui import QPen, QColor, QBrush, QRadialGradient, QGradient, QPainter, QPixmap, QIcon
import os

from styles.colours import DARK_BG, CHART_BG


class CirclesWidget(QChartView):
    def __init__(self, x_values=None, y_values=None, pacer_color=None, breathing_color=None, hr_color=None, background_image=None):
        super().__init__()

        # Background image
        self.background_image = None
        if background_image:
            # Make sure the image file exists
            if os.path.exists(background_image):
                print(f"Image file exists at path: {background_image}")
                self.background_image = QPixmap(background_image)
                print(f"Image loaded successfully: {not self.background_image.isNull()}")
                print(f"Image dimensions: {self.background_image.width()}x{self.background_image.height()}")
            else:
                print(f"ERROR: Image file does not exist at path: {background_image}")
                print(f"Current working directory: {os.getcwd()}")
                # Try to find the image in nearby directories
                for root, dirs, files in os.walk('.', topdown=True):
                    for file in files:
                        if file == os.path.basename(background_image):
                            full_path = os.path.join(root, file)
                            print(f"Found similar file at: {full_path}")
        
        # Enforce square aspect ratio via sizeHint
        self.setSizePolicy(
            QSizePolicy(
                QSizePolicy.Preferred,  # Changed from Fixed to Preferred
                QSizePolicy.Preferred,
            )
        )

        # Dark mode styling
        self.setBackgroundBrush(QBrush(DARK_BG))
        self.scene().setBackgroundBrush(QBrush(DARK_BG))
        self.setAlignment(Qt.AlignCenter)

        # Create chart
        self.plot = QChart()
        self.plot.legend().setVisible(False)
        self.plot.setBackgroundRoundness(10)
        self.plot.setMargins(QMargins(0, 0, 0, 0))

        # Set up chart background
        if self.background_image and not self.background_image.isNull():
            # Use the image as chart background with gradient overlay
            self.apply_background_image_to_chart()
        else:
            # Chart radial gradient background (fallback)
            gradient = QRadialGradient(0.5, 0.5, 0.5)
            gradient.setCoordinateMode(QGradient.ObjectBoundingMode)
            gradient.setColorAt(0, QColor(50, 50, 60))
            gradient.setColorAt(1, QColor(30, 30, 40))
            self.plot.setBackgroundBrush(QBrush(gradient))

        # Subtle border
        borderPen = QPen(QColor(80, 80, 90))
        borderPen.setWidth(1)
        self.plot.setBackgroundPen(borderPen)

        # Drop shadow effect
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 60))
        shadow.setOffset(3, 3)
        self.setGraphicsEffect(shadow)

        # --- Pacer Disk ---
        self.pacer_circumference_coord = QSplineSeries()
        self.disk = QAreaSeries(self.pacer_circumference_coord)
        # Remove outline stroke
        self.disk.setPen(QPen(Qt.NoPen))
        # Gradient fill based on pacer_color
        if pacer_color:
            diskGradient = QRadialGradient(0, 0, 1)
            diskGradient.setCoordinateMode(QGradient.ObjectBoundingMode)
            glow = QColor(pacer_color); glow.setAlpha(200)
            dark = QColor(pacer_color).darker(150); dark.setAlpha(150)
            diskGradient.setColorAt(0, glow)
            diskGradient.setColorAt(1, dark)
            self.disk.setBrush(QBrush(diskGradient))
        else:
            self.disk.setBrush(QBrush(QColor(120, 120, 180, 180)))
        self.plot.addSeries(self.disk)

        # --- Breathing Disk ---
        self.breath_circumference_coord = QSplineSeries()
        self.breath_disk = QAreaSeries(self.breath_circumference_coord)
        # Remove outline stroke from breath disk
        self.breath_disk.setPen(QPen(Qt.NoPen))
        # Gradient fill for breath disk
        if breathing_color:
            breathGradient = QRadialGradient(0, 0, 1)
            breathGradient.setCoordinateMode(QGradient.ObjectBoundingMode)
            glow = QColor(breathing_color); glow.setAlpha(150)
            dark = QColor(breathing_color).darker(200); dark.setAlpha(100)
            breathGradient.setColorAt(0, glow)
            breathGradient.setColorAt(1, dark)
            self.breath_disk.setBrush(QBrush(breathGradient))
        else:
            self.breath_disk.setBrush(QBrush(QColor(180, 180, 240, 120)))
        self.plot.addSeries(self.breath_disk)

        # Initialize series data if provided
        if x_values is not None and y_values is not None:
            self._instantiate_series(x_values, y_values)

        # --- Axes setup (hidden) ---
        self.x_axis = QValueAxis()
        self.x_axis.setRange(-1, 1)
        self.x_axis.setVisible(False)
        self.plot.addAxis(self.x_axis, Qt.AlignBottom)
        self.disk.attachAxis(self.x_axis)
        self.breath_disk.attachAxis(self.x_axis)

        self.y_axis = QValueAxis()
        self.y_axis.setRange(-1, 1)
        self.y_axis.setVisible(False)
        self.plot.addAxis(self.y_axis, Qt.AlignLeft)
        self.disk.attachAxis(self.y_axis)
        self.breath_disk.attachAxis(self.y_axis)

        self.setChart(self.plot)
        self.setRenderHint(QPainter.Antialiasing, True)

    def _instantiate_series(self, x_values, y_values):
        for x, y in zip(x_values, y_values):
            self.pacer_circumference_coord.append(x, y)
            self.breath_circumference_coord.append(x, y)

    def update_pacer_series(self, x_values, y_values):
        for i, (x, y) in enumerate(zip(x_values, y_values)):
            self.pacer_circumference_coord.replace(i, x, y)

    def update_breath_series(self, x_values, y_values):
        for i, (x, y) in enumerate(zip(x_values, y_values)):
            self.breath_circumference_coord.replace(i, x, y)

    def apply_background_image_to_chart(self):
        """Apply the background image directly to the chart background"""
        if self.background_image.isNull():
            print("Error: Background image is null")
            return
            
        # Create a pixmap to draw on
        chart_size = self.plot.size()
        if chart_size.isEmpty():
            chart_size = QSize(400, 400)  # Default size if chart size not available
        else:
            # Convert QSizeF to QSize
            chart_size = QSize(int(chart_size.width()), int(chart_size.height()))
            
        background = QPixmap(chart_size)
        background.fill(QColor(30, 30, 40))  # Fill with dark background
        
        # Draw the lungs image onto the background
        painter = QPainter(background)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Scale the image to fit the chart
        img_rect = self.background_image.rect()
        target_rect = background.rect()
        
        scale_factor = 0.8 * min(target_rect.width() / img_rect.width(),
                               target_rect.height() / img_rect.height())
        
        new_width = int(img_rect.width() * scale_factor)
        new_height = int(img_rect.height() * scale_factor)
        
        # Center the image
        x = (target_rect.width() - new_width) // 2
        y = (target_rect.height() - new_height) // 2
        
        # Draw the image
        painter.setOpacity(0.6)  # Higher opacity of 60%
        painter.drawPixmap(x, y, new_width, new_height, self.background_image)
        
        # Apply a subtle dark gradient overlay
        gradient = QRadialGradient(target_rect.width() / 2, target_rect.height() / 2, 
                                  max(target_rect.width(), target_rect.height()) / 2)
        gradient.setColorAt(0, QColor(30, 30, 40, 100))
        gradient.setColorAt(1, QColor(20, 20, 30, 180))
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.fillRect(target_rect, gradient)
        
        painter.end()
        
        # Apply the combined background to the chart
        self.plot.setBackgroundBrush(QBrush(background))
        print(f"Applied background image at {x},{y} with size {new_width}x{new_height}")

    def set_background_image(self, image_path):
        """Set a new background image for the widget"""
        self.background_image = QPixmap(image_path)
        if not self.background_image.isNull():
            self.apply_background_image_to_chart()
        self.update()

    def paintEvent(self, event):
        # We're using the chart's background brush for the lungs image
        # Call the parent's paintEvent directly
        super().paintEvent(event)

    def sizeHint(self):
        side = self.size().height()
        return QSize(side, side)

    def resizeEvent(self, event):
        # Update the background image when the widget is resized
        if hasattr(self, 'background_image') and self.background_image and not self.background_image.isNull():
            self.apply_background_image_to_chart()
            
        if self.size().width() != self.size().height():
            self.updateGeometry()
        return super().resizeEvent(event)


class SquareWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet(f"background-color: {DARK_BG.name()};")

    def sizeHint(self):
        return QSize(100, 100)

    def resizeEvent(self, event):
        side = min(self.width(), self.height())
        self.setMaximumWidth(side)
        self.setMaximumHeight(side)
        return super().resizeEvent(event)
