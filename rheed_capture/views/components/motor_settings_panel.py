from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QGroupBox, QLineEdit, QSpinBox

from rheed_capture.models.hardware.motor_defaults import DEFAULT_POSITION_UNITS_PER_DEG


class MotorSettingsPanel(QGroupBox):
    motor_port_edited = Signal(str)
    motor_slave_changed = Signal(int)
    position_units_per_deg_changed = Signal(float)

    def __init__(self) -> None:
        super().__init__("Motor Settings")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self.edit_motor_port = QLineEdit("COM7")

        self.spin_motor_slave = QSpinBox()
        self.spin_motor_slave.setRange(1, 247)
        self.spin_motor_slave.setValue(2)

        self.spin_position_units_per_deg = QDoubleSpinBox()
        self.spin_position_units_per_deg.setRange(0.0001, 1_000_000.0)
        self.spin_position_units_per_deg.setDecimals(4)
        self.spin_position_units_per_deg.setSingleStep(0.25)
        self.spin_position_units_per_deg.setValue(DEFAULT_POSITION_UNITS_PER_DEG)

        layout.addRow("Motor Port:", self.edit_motor_port)
        layout.addRow("Motor Slave:", self.spin_motor_slave)
        layout.addRow("Position Units / deg:", self.spin_position_units_per_deg)

        self.edit_motor_port.editingFinished.connect(
            lambda: self.motor_port_edited.emit(self.edit_motor_port.text())
        )
        self.spin_motor_slave.valueChanged.connect(self.motor_slave_changed.emit)
        self.spin_position_units_per_deg.valueChanged.connect(
            self.position_units_per_deg_changed.emit
        )

    @Slot(str)
    def update_motor_port_ui(self, text: str) -> None:
        self.edit_motor_port.setText(text)

    @Slot(int)
    def update_motor_slave_ui(self, value: int) -> None:
        self.spin_motor_slave.setValue(value)

    @Slot(float)
    def update_position_units_per_deg_ui(self, value: float) -> None:
        self.spin_position_units_per_deg.setValue(value)
