from PySide6.QtCore import Qt, QMargins
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QWidget, QComboBox, QPushButton, QGraphicsDropShadowEffect
)
from PySide6.QtCharts import QChartView, QChart, QLineSeries, QScatterSeries, QSplineSeries, QAreaSeries, QValueAxis
from PySide6.QtGui import QPen, QPainter, QColor, QFont, QBrush, QGradient
from styles.colours import DARK_BG, CHART_BG, TEXT_COLOR

def create_chart(title=None, showTitle=True, showLegend=False):
    """Creates a chart with dark theme styling."""
    chart = QChart()
    
    # Dark mode styling
    chart.setBackgroundBrush(QBrush(CHART_BG))
    chart.setBackgroundRoundness(8)
    chart.setBackgroundPen(Qt.NoPen)
    
    # Remove default margins to maximize chart area
    chart.setMargins(QMargins(0, 0, 0, 0))
    chart.layout().setContentsMargins(0, 0, 0, 0)
    
    # Add padding only inside the plot area
    chart.setPlotAreaBackgroundVisible(True)
    chart.setPlotAreaBackgroundBrush(QBrush(CHART_BG.darker(110)))
    chart.setPlotAreaBackgroundPen(QPen(QColor(70, 70, 70), 1))
    
    if title and showTitle:
        chart.setTitle(title)
        title_font = QFont("Arial", 18, QFont.Bold)
        chart.setTitleFont(title_font)
        chart.setTitleBrush(QBrush(TEXT_COLOR))
    
    chart.legend().setVisible(showLegend)
    if showLegend:
        chart.legend().setLabelColor(TEXT_COLOR)
        legend_font = QFont("Arial", 14)
        chart.legend().setFont(legend_font)
        # Position legend at the bottom to save horizontal space
        chart.legend().setAlignment(Qt.AlignBottom)
    
    # Add drop shadow for modern look
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(15)
    shadow.setColor(QColor(0, 0, 0, 80))
    shadow.setOffset(3, 3)
    chart.setGraphicsEffect(shadow)
    
    return chart

def create_scatter_series(color=None, size=None):
    """Creates a scatter series with specified color and marker size."""
    series = QScatterSeries()
    if color:
        series.setColor(color)
    if size:
        series.setMarkerSize(size)
    return series

def create_line_series(color=None, width=1.0):
    """Creates a line series with specified color and width."""
    series = QLineSeries()
    if color:
        pen = QPen(color)
        pen.setWidth(width)
        series.setPen(pen)
    return series

def create_spline_series(color=None, width=1.0):
    """Creates a spline series with specified color and width."""
    series = QSplineSeries()
    if color:
        pen = QPen(color)
        pen.setWidth(width)
        series.setPen(pen)
    return series

def create_axis(title=None, color=None, tickCount=None, 
              labelFormat=None, rangeMin=None, rangeMax=None, labelSize=None, 
              flip=None):
    """Creates a chart axis with dark theme styling."""
    axis = QValueAxis()
    
    if title:
        axis.setTitleText(title)
        title_brush = QBrush(TEXT_COLOR if color is None else color)
        axis.setTitleBrush(title_brush)
        if labelSize:
            title_font = QFont("Arial", labelSize, QFont.Bold)
            axis.setTitleFont(title_font)
    
    # Dark mode styling for grid lines and labels
    axis.setGridLineColor(QColor(70, 70, 70))  # Darker grid lines
    axis.setGridLineVisible(True)
    axis.setMinorGridLineVisible(False)  # Turn off minor grid lines to reduce clutter
    axis.setLabelsColor(TEXT_COLOR)
    axis.setLinePen(QPen(QColor(120, 120, 120)))  # Axis line color
    
    # Optimize label size for compact views
    if labelSize:
        labelSize = min(labelSize, 16)  # Cap label size for compact views
        label_font = QFont("Arial", labelSize)
        axis.setLabelsFont(label_font)
    
    # Reduce the number of tick marks in compact views
    if tickCount:
        # Use fewer ticks to avoid crowding
        adjusted_ticks = min(tickCount, 6)
        axis.setTickCount(adjusted_ticks)
    else:
        axis.setTickCount(5)  # Default to 5 ticks for compact views
    
    if labelFormat:
        axis.setLabelFormat(labelFormat)
    if rangeMin is not None and rangeMax is not None:
        axis.setRange(rangeMin, rangeMax)
    if flip is not None:
        axis.setReverse(flip)
    
    return axis