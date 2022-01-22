from odoo_automation import automation, conveyor, automation_web, dispenser
import logging, odoorpc, threading, time, argparse, configparser, serial
from odoo_automation import motion_control_BTT_GTR as motion_control
import digitalio, board, busio #blinka libs
import RPi.GPIO as GPIO #RPi libs for interupts
import numpy as np
from adafruit_mcp230xx.mcp23017 import MCP23017
import adafruit_ads1x15
import adafruit_pca9685


#setup up i/o devices
_i2c_1 = busio.I2C(board.SCL, board.SDA)
_mcp20 = MCP23017(_i2c_1, address=0x20)
#_ads48 = adafruit_ads1x15.ads1115.ADS1115(address=0x48, busnum=1)
_pca = adafruit_pca9685.PCA9685(_i2c_1, address=0x40)
_pca.frequency = 60

#setup logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
_logger = logging.getLogger("Epoxy Dispenser")

class MRP_machine(automation.MRP_Automation, automation_web.Automation_Webservice):
    
    def __init__(self, api, config):
        #init conveyor for this machine
        self.conveyor_1 = Conveyor_1(config["conveyor_1"])
        
        #setup button pins
        self.button_start_input = digitalio.DigitalInOut(board.D6)
        self.button_start_input.direction = digitalio.Direction.INPUT
        self.button_start_input.pull = digitalio.Pull.UP
        
        self.button_stop_input = digitalio.DigitalInOut(board.D5)
        self.button_stop_input.direction = digitalio.Direction.INPUT
        self.button_stop_input.pull = digitalio.Pull.UP
        
        self.button_estop_input = digitalio.DigitalInOut(board.D23)
        self.button_estop_input.direction = digitalio.Direction.INPUT
        self.button_estop_input.pull = digitalio.Pull.UP
        
        self.door_locks_safe = digitalio.DigitalInOut(board.D24)
        self.door_locks_safe.direction = digitalio.Direction.INPUT
        self.door_locks_safe.pull = digitalio.Pull.UP
        
        self.button_start_led = digitalio.DigitalInOut(board.D13)
        self.button_start_led.direction = digitalio.Direction.OUTPUT
        self.button_start_led.value = 0
        
        self.button_warn_led = digitalio.DigitalInOut(board.D25)
        self.button_warn_led.direction = digitalio.Direction.OUTPUT
        self.button_warn_led.value = 0
        
        self.button_estop_relay = digitalio.DigitalInOut(board.D26)
        self.button_estop_relay.direction = digitalio.Direction.OUTPUT
        self.button_estop_relay.value = 1
        
        self.door_locks = digitalio.DigitalInOut(board.D27)
        self.door_locks.direction = digitalio.Direction.OUTPUT
        self.door_locks.value = 1
        
        self.nRESET = digitalio.DigitalInOut(board.D4)
        self.nRESET.direction = digitalio.Direction.OUTPUT
        self.nRESET.value = 1
        
        port = serial.Serial('/dev/ttyACM0', baudrate=115200)
        self.motion_control = motion_control.MotonControl(port)
        self.motion_control_lock = threading.Lock()
        self.motion_control.axis_to_home = ["Y", "Z"]
        self.motion_control.home()
        self.motion_control.wait_for_movement()
        
        super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']), config)
        
        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self), MRP_Carrier_Lane_1(self.api, self)]
        
        self.dispenser = FRC_advantage(api, config['dispenser'])
        
        self.button_input_thread = threading.Thread(target=self.button_input_loop, daemon=True)
        self.button_input_thread.start()
        
        _logger.info("Machine INIT Compleete.")
        #self.start_webservice()
        return
        
    def button_input_loop(self):
        while True:
            try:
                if not self.button_start_input.value:
                    self.button_start()
                
                if not self.button_stop_input.value:
                    self.button_stop()
                    
                if not self.button_estop_input.value:
                    #self.e_stop()
                    pass
                    
                if self.button_estop_input.value and self.e_stop_status == True:
                    self.e_stop_reset() 
            except Exception as e:
                pass
            
            time.sleep(0.1)
            
    def indicator_start(self, value):
        super(MRP_machine, self).indicator_start(value)

        self.button_start_led.value = value
        pass 
    
    def indicator_warn(self, value):
        super(MRP_machine, self).indicator_warn(value)
        self.button_warn_led.value = value
        return 
        
    def indicator_e_stop(self, value):
        return super(MRP_machine, self).indicator_e_stop(value)
        
    
    #Button inputs
    def button_start(self):
        self.conveyor_1.start()
        
        #check and startup motion control
        if not self.motion_control.is_home:
            self.motion_control.soft_reset()
            self.motion_control.home()
            
        return super(MRP_machine, self).button_start()
    
    def button_stop(self):
        self.conveyor_1.stop()
        return super(MRP_machine, self).button_stop()
    
    def e_stop(self):
        #put render safe i/o here.
        self.conveyor_1.e_stop()
        return super(MRP_machine, self).e_stop()
    
    def e_stop_reset(self):
        #put reboot i/o here
        self.conveyor_1.e_stop_reset()
        return super(MRP_machine, self).e_stop_reset()
        
    def quit(self):
        #set indicators to safe off state.
        self.indicator_start(False)
        self.indicator_warn(False)
        
        #send quit signals to sub components
        self.dispenser.quit()
        self.conveyor_1.quit()
        self.motion_control.quit()
        
        self.button_estop_relay.value =False
        
        return super(MRP_machine, self).quit()  
        
    #motion and machine controls
    def goto_default_location(self):
        self.motion_control.goto_position_abs(y=260,z=0.0)
    
class MRP_Carrier_Lane(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane, self).__init__(api, mrp_automation_machine)
        self.has_motion_control = False
        self.aquire_motion_control()
        self.mrp_automation_machine.motion_control.send_command(f"g92 y{self.y_zero}")
        self.release_motion_contol()
        
        #install custom carrier calss into lane
        self.carrier_class = Carrier
        
        self._logger.info("Lane INIT Complete")
        pass
    
    def aquire_motion_control(self):
        #aquire motion contol thread lock
        self.mrp_automation_machine.motion_control_lock.acquire()
        self.mrp_automation_machine.motion_control.send_command(self.datum)
        self.mrp_automation_machine.motion_control.axis_transform = self.axis_transform
        self.has_motion_control = True
        self._logger.info("Aquired Motion Contol")
        pass
        
    def release_motion_contol(self):
        self.mrp_automation_machine.motion_control.wait_for_movement()
        if self.mrp_automation_machine.motion_control_lock.locked() and self.has_motion_control:
            #return motion control to machine datum
            
            self.mrp_automation_machine.motion_control.send_command("G53")
            self.mrp_automation_machine.motion_control.axis_transform = self.mrp_automation_machine.motion_control.axis_transform_default
            self.has_motion_control = False
            self.mrp_automation_machine.motion_control_lock.release()
            self._logger.info("Released Motion Contol")
        
        pass
    
    def index_carrier(self):
        self._logger.info("Indexing carrier")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        if not self.mrp_automation_machine.motion_control.home(axis_only=self.axis_transform["A"], force=True):
            self._logger.warn("Could not index carrier")
            return False
            
        #homing was successful, re-set zero angle offset
        self.mrp_automation_machine.motion_control.send_command(f"G92 {self.axis_transform['A']}{self.a_zero}")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        return True
    
    def clear_barcode_reader(self):
        self.barcode_scanner.reset_input_buffer()
        pass
    
    def read_carrier_barcode(self):
        barcode = False
        carrier_rock = 40
        
        
        
        if self.barcode_scanner.in_waiting > 0:
            #barcode was read during indexing
            barcode = self.barcode_scanner.readline()
            return barcode
            
        self.mrp_automation_machine.motion_control.goto_position_abs(a=self.barcode_location)
        
        fail_count = 0
        
        while isinstance(barcode, bool) and fail_count < 5:
            self.mrp_automation_machine.motion_control.goto_position_rel(a=-1*carrier_rock, feed=900)
            
            self.mrp_automation_machine.motion_control.wait_for_movement()
            
            if self.barcode_scanner.in_waiting:
                barcode = self.barcode_scanner.readline()
                
            if isinstance(barcode, bool):
                self.mrp_automation_machine.motion_control.goto_position_rel(a=carrier_rock, feed=900)
                
                self.mrp_automation_machine.motion_control.wait_for_movement()
            
            if self.barcode_scanner.in_waiting:
                barcode = self.barcode_scanner.readline()
            fail_count += 1
                
        if not isinstance(barcode, bool):
            barcode = barcode.decode('utf-8').replace('\r\n',"")
            
        
        return barcode
        
    #main loop functions
    def preflight_checks(self):
        #check that the machine is ready to accept a product.
        if not self.ingress_end_stop.value:
            self._logger.warn("Carrier End Stop trigger, a carrier may be trapped in the machine.")
            return False
        
        return True
        
    def ingress_trigger(self):
        return not self.input_ingress.value
        
    def process_ingress(self):
        
        #open ingress gate
        self.output_carrier_capture.duty_cycle = 0x0000
        self.output_ingress_gate.duty_cycle = 0xffff
        self._logger.info("Machine opened ingress gate, waiting for product to trigger end stop")
        
        #wait for ingress end stop trigger
        time_out = time.time()
        while self.ingress_end_stop.value:
            if time_out + 10 < time.time():
                self.output_ingress_gate.duty_cycle = 0x0000
                self.warn = True
                self._logger.warn("Timeout waiting for ingress end stop trigger")
                self.release_motion_contol()
                return False
            #throttle wait peroid.
            time.sleep(0.5)
        
        self._logger.info("Product triggered endstop, closing ingress gate, capture product carrier")    
        self.output_carrier_capture.duty_cycle = 0xffff
        time.sleep(1)
        self.output_ingress_gate.duty_cycle = 0x0000
        
        #clear barcode buffer 
        self.clear_barcode_reader()
        
        self.aquire_motion_control()
        
        #wait for any movments to stop 
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        #index carrier
        if not self.index_carrier():
            self._logger.warn("Could not Index carrier.")
            self.release_motion_contol()
            return False
        
        #readin barcode
        barcode = self.read_carrier_barcode()
        
        if isinstance(barcode, bool):
            self._logger.warn("Could not scan barcode")
            self.release_motion_contol()
            return False
        
        if not self.currernt_carrier:
            #no carrier was expected.
            self.unexpected_carrier(carrier_barcode=barcode)
            
            
        if barcode != self.currernt_carrier.barcode:
            self._logger.warn("Carrier barcode did not match current carrier")
            self.unexpected_carrier(carrier_barcode=barcode)
            
        #send the carrage to y0
        self.mrp_automation_machine.motion_control.goto_position_abs(y=0.0, a=0.0)
        
        return True
    
    def process_carrier(self):
        result = super(MRP_Carrier_Lane, self).process_carrier()
        self.mrp_automation_machine.motion_control.wait_for_movement()
        return result
            
    def process_egress(self):
        self._logger.info("Machine opening egress gate, waiting to clear end stop trigger.")
        
        #put machine in a save position to egress carrier
        self.mrp_automation_machine.motion_control.goto_position_abs(z=0.0)
        
        self.release_motion_contol()
        
        #configure diverter for the destination
        destination_lane = self.currernt_carrier.carrier_history_id.route_node_lane_dest_id
        self.mrp_automation_machine.conveyor_1.diverter.divert(self.route_node_lane, destination_lane)
        
        #release carrier capture
        self.output_carrier_capture.duty_cycle = 0x0000
        
        #wait for egress end stop trigger
        time_out = time.time()
        
        while self.ingress_end_stop.value:
            if time_out + 60 < time.time():
                self._logger.warn("Timeout waiting for egress end stop trigger.")
                return False
            #throttle wait peroid.
            time.sleep(0.5)
        
        #free the diverter for other operations
        self.mrp_automation_machine.conveyor_1.diverter.clear_divert()
        
        return super(MRP_Carrier_Lane, self).process_egress()
        
    def quit(self):
        super(MRP_Carrier_Lane, self).quit()
        self.barcode_scanner.close()
        self.output_ingress_gate.duty_cycle = 0x0000
        self.output_carrier_capture.duty_cycle = 0x0000
        return True
        
class MRP_Carrier_Lane_0(MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        
        self.input_ingress = _mcp20.get_pin(4)
        self.input_ingress.direction = digitalio.Direction.INPUT
        self.input_ingress.pull = digitalio.Pull.UP
        
        self.ingress_end_stop = _mcp20.get_pin(5)
        self.ingress_end_stop.direction = digitalio.Direction.INPUT
        self.ingress_end_stop.pull = digitalio.Pull.UP
        
        self.output_ingress_gate = _pca.channels[10]
        self.output_ingress_gate.duty_cycle = False
        
        self.output_carrier_capture = _pca.channels[11]
        self.output_carrier_capture.duty_cycle = False
        duty_cycle = 0x0000
        
        self.barcode_scanner = serial.Serial('/dev/ttyACM1', baudrate=115200, rtscts=True)
        
        self.datum = "G54"
        self.y_zero = -468
        self.a_zero = -38
        self.barcode_location = 20
        self.axis_transform = {"X":"X", "Y":"Y", "Z":"Z", "A":"A", "B":"B", "C":"C"}
        
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 0")
        pass

class MRP_Carrier_Lane_1(MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        
        self.input_ingress = _mcp20.get_pin(6)
        self.input_ingress.direction = digitalio.Direction.INPUT
        self.input_ingress.pull = digitalio.Pull.UP
        
        self.ingress_end_stop = _mcp20.get_pin(7)
        self.ingress_end_stop.direction = digitalio.Direction.INPUT
        self.ingress_end_stop.pull = digitalio.Pull.UP
        
        self.output_ingress_gate = _pca.channels[5]
        self.output_ingress_gate.duty_cycle = False
        
        self.output_carrier_capture = _pca.channels[6]
        self.output_carrier_capture.duty_cycle = 0x0000
        
        self.barcode_scanner = serial.Serial('/dev/ttyACM2', baudrate=115200, rtscts=True)
        
        self.datum = "G55"
        self.y_zero = -40
        self.a_zero = 30
        self.barcode_location = 190
        self.axis_transform = {"X":"X", "Y":"Y", "Z":"Z", "A":"B", "B":"A", "C":"C"}
        
        super(MRP_Carrier_Lane_1, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 1")
        pass

class Carrier(automation.Carrier):
    def __init__(self, api, carrier_history_id, carrier_lane):
        result = super(Carrier, self).__init__(api, carrier_history_id, carrier_lane)
        self.exec_globals["motion_control"] = self.lane.mrp_automation_machine.motion_control
        self.exec_globals["dispenser"] = self.lane.mrp_automation_machine.dispenser
        pass
    
    def process_carrier(self):
        result = super(Carrier, self).process_carrier()
        self.lane.mrp_automation_machine.dispenser.wait_for_dispense()
        self.lane.mrp_automation_machine.motion_control.wait_for_movement()
        return result

class Conveyor_1(conveyor.Conveyor):
    
    def __init__(self, config):
        super(Conveyor_1, self).__init__(config=config)
        
        self.motor_p = _pca.channels[8]
        self.motor_p.duty_cycle = 0x0000
        self.motor_duty = 0x5000
        
        #setup diverter logic
        self.diverter = divert_1("Conveyor_1_Diverter")
        self.diverter.lane_diverter = {'work':{'work':self.diverter_work_work,'bypass':self.diverter_work_bypass},'bypass':{'work':self.diverter_bypass_work,'bypass':self.diverter_bypass_bypass}}
        pass
    
    def set_speed(self, freq_offset):
        duty = self.motor_duty + freq_offset
        self.motor_p.duty_cycle = duty
        self.motor_duty = duty
        
        return super(Conveyor_1, self).set_speed(freq_offset=freq_offset)
    
    def start(self):
        self.motor_p.duty_cycle = self.motor_duty
        return super(Conveyor_1, self).start()
    
    def stop(self):
        self.motor_p.duty_cycle = 0x0000
        return super(Conveyor_1, self).stop()
    
    def tach_tick(self, ch):
        new_tick = time.time()
        if self.last_tach_tick == 0:
            self.last_tach_tick = new_tick
            return
        
        pulse_len = new_tick - self.last_tach_tick
        if pulse_len > 0.8:
            self.last_tach_tick = new_tick
            self.current_ipm = round(pulse_len * self.inch_per_rpm, 1)
            self._logger.debug("Current IPM - %s" %(self.current_ipm))
            return super(Conveyor_1, self).tach_tick()

    def diverter_work_work(self):
        _logger.info("Setting Diverter from Work to Work")
        pass
    
    def diverter_work_bypass(self):
        _logger.info("Setting Diverter from Work to Bypass")
        pass
    
    def diverter_bypass_work(self):
        _logger.info("Setting Diverter from Bypass to Work")
        pass
    
    def diverter_bypass_bypass(self):
        _logger.info("Setting Diverter from Bypass to Bypass")
        pass
    
    def quit(self):
        self.stop()
        self.motor_p.duty_cycle - 0x0000
        return super(Conveyor_1, self).quit()  
        
class divert_1(conveyor.Diverter):
    def __init__(self, name):
        self.exit_door_pin = _pca.channels[9]
        self.exit_door_pin.duty_cycle = 0x0000
        self.exit_door_close_thread = threading.Thread(target=self.close_exit_door, daemon=True)
        super(divert_1, self).__init__(name)
        pass
    
    def divert(self, current_lane, destination_lane):
        self.open_exit_door()
        return super(divert_1, self).divert(current_lane, destination_lane)
            
    def clear_divert(self):
        time.sleep(1)
        return super(divert_1, self).clear_divert()
            
    def open_exit_door(self):
        self.exit_door_last_open = time.time()
        self.exit_door_pin.duty_cycle = 0xffff
        self.exit_door_close_thread = threading.Thread(target=self.close_exit_door, daemon=True).start()
        pass
        
    def close_exit_door(self):
        while self.exit_door_last_open + 20 > time.time():
            time.sleep(1)
            
        self.exit_door_pin.duty_cycle = 0x0000
        pass
    
class FRC_advantage(dispenser.FRC_advantage_ii):
    def __init__(self, api, config):
        super(FRC_advantage, self).__init__(api, config)
        
        self.ready_status = True
        
        
        self.ready_pin = _mcp20.get_pin(8)
        self.ready_pin.direction = digitalio.Direction.INPUT
        self.ready_pin.pull = digitalio.Pull.UP
        
        self.busy_pin = _mcp20.get_pin(9)
        self.busy_pin.direction = digitalio.Direction.INPUT
        self.busy_pin.pull = digitalio.Pull.UP
        
        self.material_a_low_pin = _mcp20.get_pin(11)
        self.material_a_low_pin.direction = digitalio.Direction.INPUT
        self.material_a_low_pin.pull = digitalio.Pull.UP
        
        self.material_b_low_pin = _mcp20.get_pin(12)
        self.material_b_low_pin.direction = digitalio.Direction.INPUT
        self.material_b_low_pin.pull = digitalio.Pull.UP
        
        self.start_pin = _pca.channels[4]
        self.start_pin.duty_cycle = 0
        
        self.program_bit_0_pin = _pca.channels[3]
        self.start_pin.program_bit_0_pin = 0
         
        self.program_bit_1_pin = _pca.channels[2]
        self.program_bit_1_pin.duty_cycle = 0
        
        self.program_bit_2_pin = _pca.channels[1]
        self.program_bit_2_pin.duty_cycle = 0
        
        self.program_bit_3_pin = _pca.channels[0]
        self.program_bit_3_pin.duty_cycle = 0
        
        #setup analog inputs
        # self.ads = ADS.ADS1115(i2c, address=0x48)
        # self.ads.gain = 1 #0.6666666666666666
        # self.chan0 = AnalogIn(self.ads, ADS.P0)
        # self.chan1 = AnalogIn(self.ads, ADS.P1)
        # self.chan2 = AnalogIn(self.ads, ADS.P2)
        # self.chan3 = AnalogIn(self.ads, ADS.P3)
        
        self.pressure_a_xp = [float(i) for i in config['pressure_a_xp'].split(",")]
        self.pressure_a_fp = [float(i) for i in config['pressure_a_fp'].split(",")]
        self.pressure_b_xp = [float(i) for i in config['pressure_b_xp'].split(",")]
        self.pressure_b_fp = [float(i) for i in config['pressure_b_fp'].split(",")]
        
        
        #input thread
        self.th_inputs = threading.Thread(target=self.th_input_monitor, daemon=True)
        #self.th_inputs.start()
        
        pass 
    
    def th_input_monitor(self):
        while 1:
            try:
                self._set_ready(not self.ready_pin.value)
                self._set_busy(not self.busy_pin.value)
                self._set_estop(not self.e_stop_pin.value)
                self._set_material_a_low(not self.material_a_low_pin.value)
                self._set_material_b_low(not self.material_b_low_pin.value)
            except Exception as e:
                self._logger.debug(e)
                pass
            
            #throttle bus traffic
            time.sleep(0.5)
    
    def set_e_stop(self):
        self.start_pin.duty_cycle = 0
        return super(FRC_advantage, self).set_e_stop()
    
    def _start_dispense(self):
        super(FRC_advantage, self)._start_dispense()
        self.start_pin.duty_cycle = 0xffff
        return True
        
    def _end_dispense(self):
        super(FRC_advantage, self)._end_dispense()
        self.start_pin.duty_cycle = 0x0000
        return True
    
    def set_program(self, program_number):    
        super(FRC_advantage, self).set_program(program_number)
        
        #clear out prev program outputs
        self.program_bit_0_pin.duty_cycle = 0x0000
        self.program_bit_1_pin.duty_cycle = 0x0000
        self.program_bit_2_pin.duty_cycle = 0x0000
        self.program_bit_3_pin.duty_cycle = 0x0000
        
        program_bin = f"{program_number:05b}"
        
        if bool(int(program_bin[4])):
            self.program_bit_0_pin.duty_cycle = 0xffff
            
        if bool(int(program_bin[3])):
            self.program_bit_1_pin.duty_cycle = 0xffff
            
        if bool(int(program_bin[2])):
            self.program_bit_2_pin.duty_cycle = 0xffff
            
        if bool(int(program_bin[1])):
            self.program_bit_3_pin.duty_cycle = 0xffff
        
        
        #dwell time for machine to update program
        time.sleep(0.5)
        return True
        
    @property
    def pressure_a(self):
        pressure = np.interp(self.chan0.value, xp=self.pressure_a_xp, fp=self.pressure_a_fp)
        return round(pressure, 0)
        
    @property
    def pressure_b(self):
        pressure = np.interp(self.chan1.value, xp=self.pressure_b_xp, fp=self.pressure_b_fp)
        return round(pressure, 0)
        
    def quit(self):
        self.start_pin.value = 0
        self.program_bit_0_pin.value = 0
        self.program_bit_1_pin.value = 0
        self.program_bit_2_pin.value = 0
        self.program_bit_3_pin.value = 0
        
        return super(FRC_advantage, self).quit()    

def create_odoo_api():
    #create odoo api object
    try:
        odoo = odoorpc.ODOO(config['odoo']['server_url'], port=config['odoo']['tcp_port'])
        odoo.login(config['odoo']['database'], config['odoo']['username'], config['odoo']['password'])
        _logger.info("Loggedin to ODOO server %s as %s" % (config['odoo']['database'], config['odoo']['username']))
        return odoo
    except Exception as e:
        _logger.error(e)
        exit(-1)
        pass

def read_config():
    #parse command line args
    try:
        parser = argparse.ArgumentParser(description='')
        parser.add_argument('-c', type=str, help='Configuration file path')
        args = parser.parse_args()
        
        #parse config file args
        config = configparser.ConfigParser()
        config.readfp( open(args.c) ) #open the config file listed in command line arg c
        _logger.info("Read config file %s" % (args.c))
        return config
    except Exception as e:
        _logger.error(e)
        exit(-2)
        pass

if __name__ == '__main__':
    config = read_config()
    odoo_api = create_odoo_api()
    machine = MRP_machine(odoo_api, config)
    
    #uncomment for machine auto start
    #machine.button_start()
    
    while 1:
        #main thread eep alive
        time.sleep(1000)
    pass