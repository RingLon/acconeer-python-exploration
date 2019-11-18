import numpy as np
import pyqtgraph as pg

from acconeer.exptool.clients import SocketClient, SPIClient, UARTClient
from acconeer.exptool import configs
from acconeer.exptool import utils
from acconeer.exptool.pg_process import PGProcess, PGProccessDiedException


def main():
    args = utils.ExampleArgumentParser(num_sens=1).parse_args()
    utils.config_logging(args)

    if args.socket_addr:
        client = SocketClient(args.socket_addr)
    elif args.spi:
        client = SPIClient()
    else:
        port = args.serial_port or utils.autodetect_serial_port()
        client = UARTClient(port)

    sensor_config = get_sensor_config()
    sensor_config.sensor = args.sensors

    client.setup_session(sensor_config)

    pg_updater = PGUpdater(sensor_config, None)
    pg_process = PGProcess(pg_updater)
    pg_process.start()

    client.start_session()

    interrupt_handler = utils.ExampleInterruptHandler()
    print("Press Ctrl-C to end session")

    while not interrupt_handler.got_signal:
        info, data = client.get_next()

        try:
            pg_process.put_data(data)
        except PGProccessDiedException:
            break

    print("Disconnecting...")
    pg_process.close()
    client.disconnect()


def get_sensor_config():
    return configs.PowerBinServiceConfig()


class PGUpdater:
    def __init__(self, sensor_config, processing_config, session_info):
        self.sensor_config = sensor_config

        self.sweep_index = 0

    def setup(self, win):
        win.setWindowTitle("Acconeer power bins example")

        self.plot = win.addPlot(title="Power bins")
        self.plot.showGrid(x=True, y=True)
        self.plot.setLabel("bottom", "Depth (m)")
        self.plot.setLabel("left", "Amplitude")
        self.plot.setYRange(0, 1)

        self.bar_graph = pg.BarGraphItem(
            x=[],
            height=[],
            width=0,
            brush=pg.mkBrush(utils.color_cycler()),
        )

        self.plot.addItem(self.bar_graph)

        self.smooth_max = utils.SmoothMax(self.sensor_config.sweep_rate)

    def update(self, data):
        if self.sweep_index == 0:
            num_points = data.size
            self.xs = np.linspace(*self.sensor_config.range_interval, num_points * 2 + 1)[1::2]
            bin_width = 0.8 * (self.sensor_config.range_length / num_points)
            self.plot.setXRange(*self.sensor_config.range_interval)
            self.bar_graph.setOpts(x=self.xs, width=bin_width)

        self.bar_graph.setOpts(height=data)
        self.plot.setYRange(0, self.smooth_max.update(np.max(data)))

        self.sweep_index += 1


if __name__ == "__main__":
    main()