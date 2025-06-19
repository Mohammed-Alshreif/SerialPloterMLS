#Mohammed Adel Alshreif (MLS)
import sys
import serial
import serial.tools.list_ports
import csv
from datetime import datetime
import pandas as pd
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QPushButton,
    QWidget, QComboBox, QLabel, QHBoxLayout, QFileDialog,
    QTableWidget, QTableWidgetItem, QDialog, QGraphicsScene,
    QGraphicsView, QGraphicsPixmapItem
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt5.QtGui import QPixmap
import pyqtgraph as pg
import pyqtgraph.exporters
import random

class DraggableCursor(QObject):
    positionChanged = pyqtSignal()
    def __init__(self, plot_widget, color, label_prefix, get_data_callback):
        super().__init__()
        self.plot_widget = plot_widget
        self.color = color
        self.get_data = get_data_callback
        self.label_prefix = label_prefix

        self.line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(color, width=2))
        self.text = pg.TextItem("", anchor=(0, 0.5), color=color)
        self.dots = []

        self.plot_widget.addItem(self.line)
        self.plot_widget.addItem(self.text)
        self.line.sigPositionChanged.connect(self.update_position)

        self.update_position()

    def update_position(self):
        x = int(self.line.value())
        data_x, data_ys, timestamps = self.get_data()

        if 0 <= x < len(data_x):
            for dot in self.dots:
                self.plot_widget.removeItem(dot)
            self.dots.clear()

            lines = []
            timestamp = timestamps[x].strftime('%H:%M:%S.%f')[:-3]
            max_y = -float('inf')

            for i, y_data in enumerate(data_ys):
                if x < len(y_data):
                    y = y_data[x]
                    pen_color = pg.intColor(i)
                    dot = pg.ScatterPlotItem(size=10, brush=pen_color, pen=pg.mkPen(pen_color))
                    dot.setData([x], [y])
                    self.plot_widget.addItem(dot)
                    self.dots.append(dot)
                    lines.append(f"<span style='color:{pen_color.name()};'>Ch{i+1}: {y:.2f}</span>")
                    max_y = max(max_y, y)

            self.text.setHtml(f"{self.label_prefix}: {timestamp}<br>X: {x}<br>" + '<br>'.join(lines))
            self.text.setPos(x + 5, max_y)

            parent = self.plot_widget.parent()
            if parent and hasattr(parent, 'update_time_difference'):
                parent.update_time_difference()

        self.positionChanged.emit()

    def remove(self):
        for item in [self.line, self.text] + self.dots:
            self.plot_widget.removeItem(item)

    def get_time(self):
        x = int(self.line.value())
        _, _, timestamps = self.get_data()
        if 0 <= x < len(timestamps):
            return timestamps[x]
        return None

class SerialPlotter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mohammed Adel Alshreif (MLS)")
        self.resize(1000, 700)

        self.update_every_n = 10  # أضف هذا السطر هنا قبل init_ui

        self.serial = None
        self.csv_writer = None
        self.csv_file = None
        self.reading = False
        self.csv_filename = None

        self.time_stamps = []
        self.y_data_channels = []
        self.max_samples = 1000

        self.cursor1 = None
        self.cursor2 = None

        self.legend_items = []
        self.curve_visibility = []

        self.init_ui()
        self.refresh_ports()

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_plot)
        self.update_counter = 0  # أضف هذا المتغير
        self.update_every_n = 10  # حدث الرسم كل 10 عينات فقط

    def init_ui(self):
        self.port_selector = QComboBox()
        # إضافة ComboBox للـ Baudrate
        self.baudrate_selector = QComboBox()
        baudrates = [
            110, 300, 600, 1200, 2400, 4800, 9600, 14400, 19200, 38400,
            57600, 115200, 128000, 230400, 250000, 460800, 500000, 921600, 1000000,1250000, 1500000, 2000000
        ]
        for br in baudrates:
            self.baudrate_selector.addItem(str(br))
        self.baudrate_selector.setCurrentText("115200")

        # إضافة ComboBox لمعدل التحديث بقيم من 1 إلى 10 ثم 20, 30, ..., 100
        self.update_rate_selector = QComboBox()
        update_rates = [str(i) for i in range(1, 11)] + [str(i) for i in range(20, 101, 10)]
        self.update_rate_selector.addItems(update_rates)
        self.update_rate_selector.setCurrentText(str(self.update_every_n))
        self.update_rate_selector.currentTextChanged.connect(self.change_update_rate)

        # إضافة ComboBox لحجم العينات (max_samples)
        self.max_samples_selector = QComboBox()
        max_samples_options = [str(i) for i in [100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]]
        self.max_samples_selector.addItems(max_samples_options)
        self.max_samples_selector.setCurrentText(str(self.max_samples))
        self.max_samples_selector.currentTextChanged.connect(self.change_max_samples)

        self.refresh_button = QPushButton("🔄 Refresh Ports")
        self.start_button = QPushButton("▶️ Start")
        self.stop_button = QPushButton("⏹️ Stop")
        self.save_button = QPushButton("💾 Save Plot")
        self.load_csv_button = QPushButton("📂 Load CSV")
        self.open_img_button = QPushButton("🖼️ Open Image")
        self.show_table_button = QPushButton("📊 Show Table")
        self.reset_cursors_button = QPushButton("🧹 Reset Cursors")
        self.status_label = QLabel("Status: MLS")
        self.delta_label = QLabel("Δt = 0.000 sec")

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.start_button.clicked.connect(self.start_plotting)
        self.stop_button.clicked.connect(self.stop_plotting)
        self.save_button.clicked.connect(self.save_plot_image)
        self.load_csv_button.clicked.connect(self.load_csv_data)
        self.open_img_button.clicked.connect(self.open_plot_image)
        self.show_table_button.clicked.connect(self.show_data_table)
        self.reset_cursors_button.clicked.connect(self.reset_cursors)

        top_layout = QHBoxLayout()
        for widget in [
            QLabel("COM Port:"), self.port_selector, self.refresh_button,
            QLabel("Baudrate:"), self.baudrate_selector,
            QLabel("Update Rate:"), self.update_rate_selector,
            QLabel("Max Samples:"), self.max_samples_selector,  # أضف هذا السطر
            self.start_button, self.stop_button, self.save_button,
            self.load_csv_button, self.open_img_button,
            self.show_table_button, self.reset_cursors_button
        ]:
            top_layout.addWidget(widget)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setLabel('left', 'Sensor Value')
        self.plot_widget.setLabel('bottom', 'Sample Index')
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setMouseEnabled(x=True, y=True)
        self.plot_widget.scene().sigMouseClicked.connect(self.add_cursor_on_click)

        self.plot_lines = []
        self.legend = self.plot_widget.addLegend()
        self.legend_items = []
        self.curve_visibility = []

        layout = QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.delta_label)
        layout.addWidget(self.plot_widget)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        self.port_selector.clear()
        for port in ports:
            self.port_selector.addItem(port.device)

    def start_plotting(self):
        self.reset_cursors()
        selected_port = self.port_selector.currentText()
        # الحصول على قيمة البودريت المختارة
        selected_baudrate = int(self.baudrate_selector.currentText())
        if not selected_port:
            self.status_label.setText("❌ No COM port selected.")
            return

        try:
            self.csv_filename, _ = QFileDialog.getSaveFileName(
                self, "Save CSV File",
                f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV Files (*.csv)"
            )
            if not self.csv_filename:
                self.status_label.setText("⚠️ CSV save cancelled.")
                return

            # استخدم البودريت المختار هنا
            self.serial = serial.Serial(selected_port, selected_baudrate, timeout=1)
            self.csv_file = open(self.csv_filename, 'w', newline='')
            self.csv_writer = csv.writer(self.csv_file)

            self.time_stamps.clear()
            self.y_data_channels.clear()
            self.plot_widget.clear()
            self.legend = self.plot_widget.addLegend()
            self.plot_lines.clear()
            self.legend_items.clear()
            self.curve_visibility.clear()

            self.reading = True
            self.status_label.setText(f"✅ Reading from {selected_port}")
            self.timer.start(5)
        except Exception as e:
            self.status_label.setText(f"❌ Error: {str(e)}")

    def stop_plotting(self):
        self.reading = False
        self.timer.stop()
        if self.serial:
            self.serial.close()
            self.serial = None
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
        self.status_label.setText("🛑 Stopped.")
        self.update_time_difference()

    def update_plot(self):
        if not self.reading or not self.serial:
            return

        try:
            updated = False
            while self.serial.in_waiting:
                line = self.serial.readline().decode(errors='ignore').strip()
                if not line:
                    continue
                try:
                    values = [float(v) for v in line.split(',')]
                    now = datetime.now()
                    timestamp = now.strftime('%H:%M:%S.%f')[:-3]
                    self.csv_writer.writerow([timestamp] + values)

                    if not self.y_data_channels:
                        for _ in range(len(values)):
                            self.y_data_channels.append([])
                            pen = pg.mkPen(color=pg.intColor(len(self.plot_lines)), width=2)
                            plot = self.plot_widget.plot(pen=pen, name=f"Channel {len(self.plot_lines)+1}")
                            self.plot_lines.append(plot)
                            self.curve_visibility.append(True)
                        self._refresh_legend_clickable()

                    self.time_stamps.append(now)
                    for i, value in enumerate(values):
                        self.y_data_channels[i].append(value)
                        if len(self.y_data_channels[i]) > self.max_samples:
                            self.y_data_channels[i] = self.y_data_channels[i][-self.max_samples:]

                    if len(self.time_stamps) > self.max_samples:
                        self.time_stamps = self.time_stamps[-self.max_samples:]

                    self.update_counter += 1
                    if self.update_counter >= self.update_every_n:
                        for i, plot in enumerate(self.plot_lines):
                            plot.setData(list(range(len(self.y_data_channels[i]))), self.y_data_channels[i])
                        self.update_counter = 0
                        updated = True

                    if self.cursor1:
                        self.cursor1.update_position()
                    if self.cursor2:
                        self.cursor2.update_position()
                        self.update_time_difference()

                except:
                    continue
            if updated:
                QApplication.processEvents()
        except Exception as e:
            self.status_label.setText(f"⚠️ Error: {str(e)}")

    def get_data(self):
        return list(range(len(self.time_stamps))), self.y_data_channels, self.time_stamps

    def add_cursor_on_click(self, event):
        if not self.plot_widget.sceneBoundingRect().contains(event.scenePos()):
            return

        if not self.time_stamps:
            return

        x = int(self.plot_widget.plotItem.vb.mapSceneToView(event.scenePos()).x())
        if self.cursor1 is None:
            self.cursor1 = DraggableCursor(self.plot_widget, 'r', "T1", self.get_data)
            self.cursor1.positionChanged.connect(self.update_time_difference)
            self.cursor1.line.setValue(x)
        elif self.cursor2 is None:
            self.cursor2 = DraggableCursor(self.plot_widget, 'b', "T2", self.get_data)
            self.cursor2.positionChanged.connect(self.update_time_difference)
            self.cursor2.line.setValue(x)
        else:
            self.reset_cursors()
            self.cursor1 = DraggableCursor(self.plot_widget, 'r', "T1", self.get_data)
            self.cursor1.positionChanged.connect(self.update_time_difference)
            self.cursor1.line.setValue(x)

        self.update_time_difference()

    def update_time_difference(self):
        if self.cursor1 and self.cursor2:
            t1 = self.cursor1.get_time()
            t2 = self.cursor2.get_time()
            if t1 and t2:
                dt = abs((t2 - t1).total_seconds())
                self.delta_label.setText(f"Δt = {dt:.3f} sec")
            else:
                self.delta_label.setText("Δt = ---")
        else:
            self.delta_label.setText("Δt = ---")

    def reset_cursors(self):
        for cursor in [self.cursor1, self.cursor2]:
            if cursor:
                cursor.remove()
        self.cursor1 = None
        self.cursor2 = None
        self.status_label.setText("♻️ Cursors reset.")
        self.update_time_difference()

    def save_plot_image(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Save Plot", "", "PNG Files (*.png)")
        if file_name:
            exporter = pg.exporters.ImageExporter(self.plot_widget.plotItem)
            exporter.export(file_name)
            self.status_label.setText(f"💾 Plot saved: {file_name}")

    def load_csv_data(self):
        self.reset_cursors()
        file_name, _ = QFileDialog.getOpenFileName(self, "Open CSV", "", "CSV Files (*.csv)")
        if not file_name:
            return
        try:
            df = pd.read_csv(file_name)
            self.plot_widget.clear()
            self.legend = self.plot_widget.addLegend()
            self.y_data_channels = []
            self.time_stamps = pd.to_datetime(df.iloc[:, 0]).to_list()
            self.plot_lines = []
            self.legend_items = []
            self.curve_visibility = []
            for i in range(1, df.shape[1]):
                y = df.iloc[:, i].values
                self.y_data_channels.append(list(y))
                pen = pg.mkPen(color=pg.intColor(i-1), width=2)
                plot = self.plot_widget.plot(y, pen=pen, name=f"Channel {i}")
                self.plot_lines.append(plot)
                self.curve_visibility.append(True)
            self._refresh_legend_clickable()
            self.status_label.setText(f"📂 Loaded CSV: {file_name}")
        except Exception as e:
            self.status_label.setText(f"❌ Load error: {str(e)}")

    def _refresh_legend_clickable(self):
        self.legend_items.clear()
        items = []
        if hasattr(self.legend, "items"):
            if isinstance(self.legend.items, list):
                items = self.legend.items
            elif hasattr(self.legend.items, "items"):
                items = list(self.legend.items.items())
        if not items and hasattr(self, "plot_lines"):
            for i, plot in enumerate(self.plot_lines):
                label = self.legend.getLabel(plot)
                if label is not None:
                    items.append((plot, label))
        for _, label in items:
            try:
                label.removeEventFilter(self)
            except Exception:
                pass
        self.legend_items = [None] * len(items)
        for i, (sample, label) in enumerate(items):
            label.setCursor(Qt.PointingHandCursor)
            label.installEventFilter(self)
            label._legend_idx = i
            label.setAcceptHoverEvents(True)
            visible = self.plot_lines[i].isVisible() if i < len(self.plot_lines) else True
            color = pg.intColor(i).name()
            channel_name = f"Channel {i+1}"
            if visible:
                html = f"<span style='font-weight:bold; color:{color};'>{channel_name}</span>"
            else:
                html = f"<span style='color:gray;'>{channel_name}</span>"
            try:
                label.setHtml(html)
            except Exception:
                label.setText(channel_name)
            self.legend_items[i] = label

    def eventFilter(self, obj, event):
        if hasattr(obj, "_legend_idx"):
            if event.type() in (event.GraphicsSceneMousePress, event.MouseButtonPress) and event.button() == Qt.LeftButton:
                idx = obj._legend_idx
                if 0 <= idx < len(self.plot_lines):
                    current = self.plot_lines[idx].isVisible()
                    self.plot_lines[idx].setVisible(not current)
                self._refresh_legend_clickable()
                return True
            if event.type() in (event.MouseButtonDblClick, event.GraphicsSceneMouseDoubleClick):
                return True
        return super().eventFilter(obj, event)

    def toggle_curve_visibility(self, idx):
        if 0 <= idx < len(self.plot_lines):
            self.curve_visibility[idx] = not self.curve_visibility[idx]
            self.plot_lines[idx].setVisible(self.curve_visibility[idx])

    def closeEvent(self, event):
        self.stop_plotting()
        event.accept()

    def open_plot_image(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "Open Image", "", "PNG Files (*.png)")
        if not file_name:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("📷 Plot Image Viewer")
        layout = QVBoxLayout()
        pixmap = QPixmap(file_name)
        item = QGraphicsPixmapItem(pixmap)
        scene = QGraphicsScene()
        scene.addItem(item)
        view = QGraphicsView(scene)
        layout.addWidget(view)
        dialog.setLayout(layout)
        dialog.resize(800, 600)
        dialog.exec_()

    def show_data_table(self):
        if not self.y_data_channels or not self.time_stamps:
            self.status_label.setText("⚠️ No data available.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 Data Table")
        layout = QVBoxLayout()
        table = QTableWidget()
        rows = len(self.time_stamps)
        cols = len(self.y_data_channels) + 1
        table.setRowCount(rows)
        table.setColumnCount(cols)
        headers = ["Timestamp"] + [f"Ch{i+1}" for i in range(cols-1)]
        table.setHorizontalHeaderLabels(headers)
        for i in range(rows):
            table.setItem(i, 0, QTableWidgetItem(self.time_stamps[i].strftime('%H:%M:%S.%f')[:-3]))
            for j in range(len(self.y_data_channels)):
                if i < len(self.y_data_channels[j]):
                    table.setItem(i, j+1, QTableWidgetItem(str(self.y_data_channels[j][i])))
        table.resizeColumnsToContents()
        layout.addWidget(table)
        dialog.setLayout(layout)
        dialog.resize(800, 400)
        dialog.exec_()

    def change_update_rate(self, value):
        try:
            self.update_every_n = int(value)
            self.status_label.setText(f"🔄 Update rate set to {self.update_every_n}")
        except Exception:
            self.status_label.setText("⚠️ Invalid update rate")

    def change_max_samples(self, value):
        try:
            self.max_samples = int(value)
            self.status_label.setText(f"🔢 Max samples set to {self.max_samples}")
        except Exception:
            self.status_label.setText("⚠️ Invalid max samples")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SerialPlotter()
    window.show()
    sys.exit(app.exec_())
