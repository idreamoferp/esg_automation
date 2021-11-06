from odoo_automation import automation, conveyor, automation_web, dispenser
import logging, odoorpc, threading, time, argparse, configparser, serial
from odoo_automation import motion_control_BTT_GTR as motion_control
import digitalio, board, busio #blinka libs
import RPi.GPIO as GPIO #RPi libs for interupts
import numpy as np
from adafruit_mcp230xx.mcp23017 import MCP23017
import adafruit_ads1x15
import adafruit_pca9685

reset_pin = digitalio.DigitalInOut(board.D22)
reset_pin.direction = digitalio.Direction.OUTPUT
reset_pin.value = 1

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
        self.button_start_input = _mcp20.get_pin(0) #digitalio.DigitalInOut(board.D18)
        self.button_start_input.direction = digitalio.Direction.INPUT
        self.button_start_input.pull = digitalio.Pull.UP
        
        self.button_stop_input = _mcp20.get_pin(1) #digitalio.DigitalInOut(board.D6)
        self.button_stop_input.direction = digitalio.Direction.INPUT
        self.button_stop_input.pull = digitalio.Pull.UP
        
        self.button_estop_input = _mcp20.get_pin(2) #digitalio.DigitalInOut(board.D5)
        self.button_estop_input.direction = digitalio.Direction.INPUT
        self.button_estop_input.pull = digitalio.Pull.UP
        
        self.button_start_led = _pca.channels[14]
        self.button_start_led.duty_cycle = 0x0000
        
        self.button_warn_led = _pca.channels[13]
        self.button_warn_led.duty_cycle = 0x0000
        
        self.button_estop_relay = _pca.channels[15]
        self.button_estop_relay.duty_cycle = 0xffff
        
        super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']), config)
        
        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self), MRP_Carrier_Lane_1(self.api, self)]
        
        port = serial.Serial('/dev/ttyACM0', baudrate=115200)
        self.motion_control = motion_control.MotonControl(port)
        self.motion_control.axis_to_home = ["Y", "Z"]
        self.motion_control.home()
        self.motion_control.wait_for_movement()
        
        self.dispenser = FRC_advantage(api, config['dispenser'])
        
        self.button_input_thread = threading.Thread(target=self.button_input_loop, daemon=True)
        self.button_input_thread.start()
        
        _logger.info("Machine INIT Compleete.")
        #self.start_webservice()
        return
        
    def button_input_loop(self):
        while True:
            if self.button_start_input.value:
                self.button_start()
            
            if self.button_stop_input.value:
                self.button_stop()
                
            if self.button_estop_input.value:
                #self.e_stop()
                pass
                
            if not self.button_estop_input.value and self.e_stop_status == True:
                self.e_stop_reset() 
            
            time.sleep(0.1)
            
    def indicator_start(self, value):
        super(MRP_machine, self).indicator_start(value)
        if value == True:
            value = 0xffff
        self.button_start_led.duty_cycle = value
        pass 
    
    def indicator_warn(self, value):
        super(MRP_machine, self).indicator_warn(value)
        if value == True:
            value = 0xffff
        self.button_warn_led.duty_cycle = value
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
        
        return super(MRP_machine, self).quit()  
        
    #motion and machine controls
    def goto_default_location(self):
        self.motion_control.goto_position_abs(y=25,z=0.0)
    
        
class MRP_Carrier_Lane_0(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 0")
        
        self.input_ingress = _mcp20.get_pin(4)
        self.input_ingress.direction = digitalio.Direction.INPUT
        #self.input_ingress.pull = digitalio.Pull.UP
        
        self.ingress_end_stop = _mcp20.get_pin(5)
        self.ingress_end_stop.direction = digitalio.Direction.INPUT
        #self.ingress_end_stop.pull = digitalio.Pull.UP
        
        # GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # GPIO.add_event_detect(26, GPIO.BOTH, callback=self.irq_index)
        
        self.output_ingress_gate = _pca.channels[10]
        self.output_ingress_gate.duty_cycle = False
        
        self.output_carrier_capture = _pca.channels[11]
        self.output_carrier_capture.duty_cycle = 0x0000
        
        self.index_1 = 0.0
        self.index_0 = 0.0
        self.index_failures = 0
        
        self.barcode_scanner = serial.Serial('/dev/ttyACM1', baudrate=115200, rtscts=True)
        
        #install custom carrier calss into lane
        self.carrier_class = Carrier
        
        self._logger.info("Lane INIT Complete")
        pass
    
    def config_cnc_datum(self):
        command = G
        self.mrp_automation_machine.motion_control.send_command
        
    def goto_position_abs(self, y=False,z=False,a=False,feed=False,wait=True):
        return self.mrp_automation_machine.motion_control.goto_position_abs(y=y,z=z,a=a, feed=feed, wait=wait)
    def goto_position_rel(self, y=False,z=False,a=False,feed=False,wait=True):
        return self.mrp_automation_machine.motion_control.goto_position_rel(y=y,z=z,a=a, feed=feed,wait=wait)
    
        
    def index_carrier(self):
        self._logger.info("Indexing carrier")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        # self.mrp_automation_machine.motion_control.send_command("G38.2x680f6000")
        # self.mrp_automation_machine.motion_control.send_command("G92x0")
        # self.mrp_automation_machine.motion_control.send_command("G0x-40")
        # self.mrp_automation_machine.motion_control.send_command("G28A")
        # self.mrp_automation_machine.motion_control.send_command("G0A0")
        
        
        
        if not self.mrp_automation_machine.motion_control.home(axis_only="A", force=True):
            self._logger.warn("Could not index carrier")
            return False
            
        #homing was successful, re-set zero angle offset
        self.mrp_automation_machine.motion_control.send_command("G92 A-38")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        return True
    
    def clear_barcode_reader(self):
        self.barcode_scanner.reset_input_buffer()
        pass
    
    def read_carrier_barcode(self):
        barcode = False
        
        barcode_start_position = 0
        self.goto_position_abs(a=barcode_start_position)
        
        if self.barcode_scanner.in_waiting > 0:
            #barcode was read during indexing
            barcode = self.barcode_scanner.readline()
        fail_count = 0
        
        while isinstance(barcode, bool) and fail_count < 5:
            self.goto_position_abs(a=-15 + barcode_start_position, feed=900)
            
            self.mrp_automation_machine.motion_control.wait_for_movement()
            
            if self.barcode_scanner.in_waiting:
                barcode = self.barcode_scanner.readline()
                
            if isinstance(barcode, bool):
                self.goto_position_rel(a=15 + barcode_start_position, feed=900)
                
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
        if self.ingress_end_stop.value:
            self._logger.warn("Carrier End Stop trigger, a carrier may be trapped in the machine.")
            return False
        
        return True
        
    def ingress_trigger(self):
        return self.input_ingress.value
        
    def process_ingress(self):
        
        #open ingress gate
        self.output_carrier_capture.duty_cycle = 0x0000
        self.output_ingress_gate.duty_cycle = 0xffff
        self._logger.info("Machine opened ingress gate, waiting for product to trigger end stop")
        
        #positioning machine to lane zero
        self.mrp_automation_machine.motion_control.send_command("G1f3000 Y468Z0")
        self.mrp_automation_machine.motion_control.send_command("G54")
        self.mrp_automation_machine.motion_control.send_command("G92 Y0")
        self.goto_position_abs(y=0,z=0)
        
        #wait for ingress end stop trigger
        time_out = time.time()
        while not self.ingress_end_stop.value:
            if time_out + 60 < time.time():
                self.output_ingress_gate.duty_cycle = 0x0000
                self.warn = True
                self._logger.warn("Timeout waiting for ingress end stop trigger")
                return False
            #throttle wait peroid.
            time.sleep(0.5)
        
        self._logger.info("Product triggered endstop, closing ingress gate, capture product carrier")    
        self.output_carrier_capture.duty_cycle = 0xffff
        time.sleep(1)
        self.output_ingress_gate.duty_cycle = 0x0000
        
        
        #clear barcode buffer 
        self.clear_barcode_reader()
        
        #index carrier
        if not self.index_carrier():
            self._logger.warn("Could not Index carrier.")
            return False
        
        #readin barcode
        barcode = self.read_carrier_barcode()
        
        if isinstance(barcode, bool):
            self._logger.warn("Could not scan barcode")
            return False
        
        if not self.currernt_carrier:
            #no carrier was expected.
            self.unexpected_carrier(carrier_barcode=barcode)
            return True
            
        if barcode != self.currernt_carrier.barcode:
            self._logger.warn("Carrier barcode did not match current carrier")
            self.unexpected_carrier(carrier_barcode=barcode)
            return True
        
        #wait for all motion to compleete
        self.goto_position_abs(a=0.0)
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        
        return True
    
    def process_carrier(self):
        result = super(MRP_Carrier_Lane_0, self).process_carrier()
        self.mrp_automation_machine.motion_control.wait_for_movement()
        return result
            
    def process_egress(self):
        self._logger.info("Machine opening egress gate, waiting to clear end stop trigger.")
        
        #wait for any lingering movments during process_carrier()
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        #return motion control to machine datum
        self.mrp_automation_machine.motion_control.send_command("G53")
        
        #put machine in a save position to egress carrier
        self.goto_position_abs(z=0.0)
        time.sleep(1)
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        #configure diverter for the destination
        destination_lane = self.currernt_carrier.carrier_history_id.route_node_lane_dest_id
        self.mrp_automation_machine.conveyor_1.diverter.divert(self.route_node_lane, destination_lane)
        
        #release carrier capture
        self.output_carrier_capture.duty_cycle = 0x0000
        
        #wait for egress end stop trigger
        time_out = time.time()
        while not self.ingress_end_stop.value:
            if time_out + 60 < time.time():
                self._logger.warn("Timeout waiting for egress end stop trigger.")
                return False
            #throttle wait peroid.
            time.sleep(0.5)
        
        #free the diverter for other operations
        self.mrp_automation_machine.conveyor_1.diverter.clear_divert()
        
        return super(MRP_Carrier_Lane_0, self).process_egress()
        
    def quit(self):
        super(MRP_Carrier_Lane_0, self).quit()
            
        self.output_ingress_gate.duty_cycle = 0x0000
        self.output_carrier_capture.duty_cycle = 0x0000
        return True
    
class MRP_Carrier_Lane_1(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane_1, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 1")
        self._logger.info("Lane INIT Complete")
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
        
        self.motor_p = _pca.channels[12]
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
        return super(divert_1, self).__init__(name)
    
    def divert(self, current_lane, destination_lane):
        self.open_exit_door()
        return super(divert_1, self).divert(current_lane, destination_lane)
            
    def clear_divert(self):
        time.sleep(5)
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