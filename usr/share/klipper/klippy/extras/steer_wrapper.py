import logging
import json
import os

key_timeout = """!! {"code":"key831", "msg":"serial_485 communication timeout", "values": [%d]}"""
key_params_err = """!! {"code":"key834", "msg":"params error, send data: %s", "values": []}"""

# with box communicate cmd
Box_cmd = {
    "CREATE_CONNECT": b'\x01',
    "CPU_RESET": b'\x56',
    "GET_STATE": b'\x0A',
    "GET_CAMERA_MODULE": b'\x80',
}

TIMEOUT_SHORT_TIME = 2
TIMEOUT_LONG_TIME = 150
TIMEOUT_LONGER_TIME =300
TIMEOUT_MAX = 3600

cmd_timeout = {
    "CREATE_CONNECT": TIMEOUT_SHORT_TIME,
    "GET_STATE": TIMEOUT_MAX,
    "CPU_RESET": TIMEOUT_SHORT_TIME,
    "GET_CAMERA_MODULE": TIMEOUT_SHORT_TIME,
    "SET_BOX_MODE": TIMEOUT_SHORT_TIME,
}

state = {"OK": 0x00, "PARAMS_ERR": 0x01, "CRC_ERR": 0x02, "STATE_ERR": 0x03,}


HEAD_POS=0
ADDR_POS=1
LEN_POS=2
STATE_POS=3
CMD_POS=4
DATA_POS=5
BOX_NUM_POS=1
MATERIAL_NUM_POS=2

class State:
    def __init__(self):
        self.connected = False
        self.enable = False
class Service:
    def __init__(self, config, state):
        self.print_stats = None
        self._serial = None
        self.toolhead = None
        self.config = config
        self.printer = self.config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = config.get_printer().lookup_object('gcode')
        self.state = state

        self.printer.register_event_handler("klippy:shutdown", self._handle_shutdown)
        self.printer.register_event_handler('klippy:ready', self._handle_ready)

    def enable_heart_process(self):
        self.state.enable = 1

    def disable_heart_process(self):
        self.state.enable = 1

    def _handle_shutdown(self):
        self.is_shutdown = True

    def _handle_ready(self):
        self.is_shutdown = False
        self.find_objs()

    def find_objs(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        self._serial = self.printer.lookup_object("serial_485 " + "serial485")
        self.print_stats = self.printer.lookup_object('print_stats')

    def error(self):
        pass

    def get_key_from_value(self, dict, v):
        for key, value in dict.items():
            if value == v:
                return key
        return None

    def parse_num_to_byte(self, data):
        byte_string =bytes([data])
        return byte_string

    def ret_parse_process(self, data_send, msg):
        msg_pos = {"HEAD": 0, "ADDR": 1, "LEN": 2, "STATE": 3, "CMD": 4, "DATA": 5}
        msg_string = ' '.join(hex(byte) for byte in msg)
        logging.info("msg: %s" % msg_string)
        ret_state = msg[msg_pos["STATE"]]
        ret_key = self.get_key_from_value(state, ret_state)
        logging.info("state: %s[0x%x]" % (ret_key, ret_state))
        # if ret_state == state["OK"]:
        #     self.process_msg(data_send, msg)
        return ret_key
    def timeout_process(self, addr):
        if self.state.connected:
            if self.state.enable == 1:
                # reactor error
                # error(key_timeout%(addr), self.gcode, self.reactor, self.print_stats.state, self.box_save)
                pass
            self.state.connected = False

    # params is bytes string
    def send_data(self, addr, cmd, timeout, state=b'\xff', data=b'', report_err=True):
        data_send = None
        num_map = {0x01: 'A', 0x02: 'B', 0x04: 'C', 0x08: 'D', 0x00: '0', 0x0f: '0'}
        if len(data) == 0:
            data_send = addr + self.parse_num_to_byte(1 + len(cmd) + 1) + state + cmd
        else:
            data_send = addr + self.parse_num_to_byte(1 + len(cmd) + len(data) + 1) + state + cmd + data
        send_data_string = ' '.join(hex(byte) for byte in data_send)
        logging.info("data_send: %s" % send_data_string)
        times = 1 if timeout >= TIMEOUT_MAX else 5
        ret = True
        while True:
            params = self._serial.cmd_send_data_with_response(data_send, timeout)
            # if cmd == Box_cmd["COMMUNICATION_TEST"]:
            #     ret = params[DATA_POS] if params else None
            #     return ret
            if params is None:
                if cmd == Box_cmd["GET_STATE"]:
                    return None
                else:
                    self.timeout_process(int.from_bytes(addr, byteorder='big'))
                return False
            ret_state = self.ret_parse_process(data_send, params)

            if ret_state == "OK":
                ret = True
                break
            elif ret_state == "PARAMS_ERR":
                self.error()
                return False
            elif ret_state == "CRC_ERR" or ret_state == "LENGTH_ERR":
                # transmit error, retry
                if times < 0:
                    return False
                times -= 1
                continue
        return ret

    def communication_create_connect(self, addr):
        cmd = Box_cmd["CREATE_CONNECT"] # byte string
        return self.send_data(self.parse_num_to_byte(addr), cmd, cmd_timeout["CREATE_CONNECT"])

    def communication_get_state(self, addr):
        cmd = Box_cmd["GET_STATE"]
        return self.send_data(self.parse_num_to_byte(addr), cmd, cmd_timeout["GET_STATE"])


    def communication_cpu_reset(self, addr):
        cmd = Box_cmd["CPU_RESET"]
        return self.send_data(self.parse_num_to_byte(addr), cmd, cmd_timeout["CPU_RESET"])


    def communication_camera_module(self, addr):
        cmd = Box_cmd["GET_CAMERA_MODULE"]
        return self.send_data(self.parse_num_to_byte(addr), cmd, cmd_timeout["GET_CAMERA_MODULE"])


class SteerWrapper:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        self.webhooks = self.printer.lookup_object('webhooks')

        self.gcode.register_command('STEER_CREATE_CONNECT', self.cmd_create_connect)
        self.gcode.register_command('STEER_GET_STATE', self.cmd_get_state)
        self.gcode.register_command('STEER_CPU_RESET', self.cmd_cpu_reset)
        self.gcode.register_command('STEER_CAMERA_MODULE', self.cmd_camera_module)
        self.printer.register_event_handler('klippy:ready', self.find_objs)
        self.state = State()
        self.service = Service(config, self.state)

    def find_objs(self):
        self.reactor.register_callback(self.heart_process)
    def heart_process(self, eventtime):
        max_time = 5
        timeout_times = 5
        addr = 0x41
        while True:
            if self.printer.is_shutdown():
                return
            ret = self.service.communication_get_state(addr)
            if ret is None:
                timeout_times -= 1
            else:
                timeout_times = max_time
                self.state.connected = True

            if timeout_times <= 0:
                self.service.timeout_process(addr)
            self.reactor.pause(self.reactor.monotonic() + 5.)
            
    def cmd_create_connect(self,gcmd):
        addr = gcmd.get_int("ADDR", 0)
        if addr == 0:
            addr = 0x41
        if not self.state.connected:
            gcmd.respond_info("Steer not connected")
            return
        self.service.communication_create_connect(addr)
        
    def cmd_get_state(self, gcmd):
        addr = gcmd.get_int("ADDR", 0)
        if addr == 0:
            addr = 0x41
        self.service.communication_get_state(addr)

    def cmd_cpu_reset(self, gcmd):
        addr = gcmd.get_int("ADDR", 0)
        if addr == 0:
            addr = 0x41
        if not self.state.connected:
            gcmd.respond_info("Steer not connected")
            return
        self.service.communication_cpu_reset(addr)
    def cmd_camera_module(self, gcmd):
        addr = gcmd.get_int("ADDR",0)
        if addr == 0:
            addr = 0x41
        if not self.state.connected:
            gcmd.respond_info("Steer not connected")
            return
        self.service.communication_camera_module(addr)

    def get_status(self, eventime):
        result = dict()
        result['state'] = self.state.connected
        result['enable'] = self.state.enable
        return result

