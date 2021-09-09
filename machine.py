import automation, conveyor, automation_web, dispenser
import logging, odoorpc, threading, time, argparse, configparser, serial
import motion_control_grbl as motion_control
import digitalio, board, busio #blinka libs
import RPi.GPIO as GPIO #RPi libs for interupts

from adafruit_mcp230xx.mcp23017 import MCP23017
i2c = busio.I2C(board.SCL, board.SDA)
mcp20 = MCP23017(i2c, address=0x20)
#mcp21 = MCP23017(i2c, address=0x21)


#setup logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
_logger = logging.getLogger("Test Machine")

class TestMachine(automation_web.Automation_Webservice, automation.MRP_Automation):
    
    def __init__(self, api, asset_id):
        
        
        #init conveyor for this machine
        self.conveyor_1 = Conveyor_1()
        self.conveyor_1.set_ipm = 10
        
        #setup button pins
        self.button_start_input = digitalio.DigitalInOut(board.D18)
        self.button_start_input.direction = digitalio.Direction.INPUT
        self.button_start_input.pull = digitalio.Pull.DOWN
        
        self.button_stop_input = digitalio.DigitalInOut(board.D6)
        self.button_stop_input.direction = digitalio.Direction.INPUT
        self.button_stop_input.pull = digitalio.Pull.DOWN
        
        self.button_estop_input = digitalio.DigitalInOut(board.D5)
        self.button_estop_input.direction = digitalio.Direction.INPUT
        self.button_estop_input.pull = digitalio.Pull.DOWN
        
        self.button_start_led = digitalio.DigitalInOut(board.D26)
        self.button_start_led.direction = digitalio.Direction.OUTPUT
        
        self.button_warn_led = digitalio.DigitalInOut(board.D27)
        self.button_warn_led.direction = digitalio.Direction.OUTPUT
        
        self.button_estop_led = digitalio.DigitalInOut(board.D4)
        self.button_estop_led.direction = digitalio.Direction.OUTPUT
        
        super(TestMachine, self).__init__(api, asset_id)
        
        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self), MRP_Carrier_Lane_1(self.api, self)]
        
        
        
        # self.dispenser = dispenser.FRC_advantage_ii()
        # self.dispenser.trigger_output = mcp20.get_pin(0)
        # self.dispenser.trigger_output.direction = digitalio.Direction.OUTPUT
        # self.dispenser.trigger_output.value = False
        
        self.motion_control = motion_control.MotonControl('/dev/serial0')
        
        self.button_input_thread = threading.Thread(target=self.button_input_loop, daemon=True)
        self.button_input_thread.start()
        
        
        self.motion_control.home()
        self.goto_default_location()
        
        
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
                self.e_stop()
                
            if not self.button_estop_input.value and self.e_stop_status == True:
                self.e_stop_reset() 
            
            if len(self.motion_control.errors) and self.run_status:
                _logger.error("Motion Control has errors")
                self.button_stop()
                self.machine_warn = True
            time.sleep(0.1)
            
    def indicator_start(self, value):
        self.button_start_led.value = value
        return super(TestMachine, self).indicator_start(value)
    
    def indicator_warn(self, value):
        self.button_warn_led.value = value
        return super(TestMachine, self).indicator_warn(value)
        
    def indicator_e_stop(self, value):
        self.button_estop_led.value = not value
        return super(TestMachine, self).indicator_e_stop(value)
        
    
    #Button inputs
    def button_start(self):
        self.conveyor_1.start()
        
        #check and startup motion control
        if not self.motion_control.is_home:
            self.motion_control.soft_reset()
            self.motion_control.home()
            
        return super(TestMachine, self).button_start()
    
    def button_stop(self):
        self.conveyor_1.stop()
        return super(TestMachine, self).button_stop()
    
    def e_stop(self):
        #put render safe i/o here.
        self.conveyor_1.e_stop()
        return super(TestMachine, self).e_stop()
    
    def e_stop_reset(self):
        #put reboot i/o here
        self.conveyor_1.e_stop_reset()
        return super(TestMachine, self).e_stop_reset()
        
    def quit(self):
        #set indicators to safe off state.
        self.indicator_start(False)
        self.indicator_warn(False)
        
        #send quit signals to sub components
        self.conveyor_1.quit()
        
        i2c.deinit()
        return super(TestMachine, self).quit()  
        
    #motion and machine controls
    def goto_default_location(self):
        self.motion_control.goto_position_abs(y=325,z=0.0)
    
        
class MRP_Carrier_Lane_0(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        self._logger = logging.getLogger("Carrier Lane 0")
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        
        self.input_ingress = mcp20.get_pin(11)
        self.input_ingress.direction = digitalio.Direction.INPUT
        #self.input_ingress.pull = digitalio.Pull.UP
        
        self.ingress_end_stop = mcp20.get_pin(8)
        self.ingress_end_stop.direction = digitalio.Direction.INPUT
        #self.ingress_end_stop.pull = digitalio.Pull.UP
        
        # GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # GPIO.add_event_detect(26, GPIO.BOTH, callback=self.irq_index)
        
        self.output_ingress_gate = mcp20.get_pin(7)
        self.output_ingress_gate.direction = digitalio.Direction.OUTPUT
        self.output_ingress_gate.value = False
        
        self.output_carrier_capture = mcp20.get_pin(6)
        self.output_carrier_capture.direction = digitalio.Direction.OUTPUT
        self.output_carrier_capture.value = False
        
        self.index_1 = 0.0
        self.index_0 = 0.0
        self.index_failures = 0
        
        self.barcode_scanner = serial.Serial('/dev/ttyUSB0', baudrate=115200, rtscts=True)
        self._logger.info("Lane INIT Complete")
        pass
    
    def goto_position_abs(self, y=False,z=False,a=False,feed=False,wait=False):
        return self.mrp_automation_machine.motion_control.goto_position_abs(x=a,y=y,z=z,feed=feed, wait=wait)
    def goto_position_rel(self, y=False,z=False,a=False,feed=False,wait=False):
        return self.mrp_automation_machine.motion_control.goto_position_rel(x=a,y=y,z=z,feed=feed,wait=wait)
    
    def irq_index(self, ch):
        value = GPIO.input(ch)
        cord = float(self.mrp_automation_machine.motion_control.mach_position_x)
        if self.index_0 == 0.0:
            self.index_0 = cord
            
            return
        else:
            self.index_1 = cord
            
            return
        pass
        
    def index_carrier(self):
        self._logger.info("Indexing carrier")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        self.mrp_automation_machine.motion_control.send_command("G38.2x680f6000")
        self.mrp_automation_machine.motion_control.send_command("G92x0")
        self.mrp_automation_machine.motion_control.send_command("G0x-40")
        self.mrp_automation_machine.motion_control.send_command("G38.2x50f900")
        self.mrp_automation_machine.motion_control.send_command("G92x-40")
        self.mrp_automation_machine.motion_control.send_command("G0x0")
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        if len(self.mrp_automation_machine.motion_control.errors) > 0:
            return False
            
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
        self.output_carrier_capture.value = False
        self.output_ingress_gate.value = True
        self._logger.info("Machine opened ingress gate, waiting for product to trigger end stop")
        
        #positioning machine to lane zero
        self.mrp_automation_machine.motion_control.work_offset(y=530)
        self.goto_position_abs(y=0,z=0)
        
        #wait for ingress end stop trigger
        time_out = time.time()
        while not self.ingress_end_stop.value:
            if time_out + 60 < time.time():
                self.output_ingress_gate.value = True
                self.warn = True
                self._logger.warn("Timeout waiting for ingress end stop trigger")
                return False
            #throttle wait peroid.
            time.sleep(0.5)
        
        self._logger.info("Product triggered endstop, closing ingress gate, capture product carrier")    
        self.output_carrier_capture.value = True
        time.sleep(1)
        self.output_ingress_gate.value = False
        
        
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
            self.unexpected_carrier(barcode)
            return False
            
        if barcode != self.currernt_carrier.barcode:
            self._logger.warn("Carrier barcode did not match current carrier")
            self.unexpected_carrier(barcode)
            return False
        
        #wait for all motion to compleete
        self.goto_position_abs(a=0.0)
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        
        return True
        
    def process_egress(self):
        self._logger.info("Machine opening egress gate, waiting to clear end stop trigger.")
        
        
        #put the machine in a safe location
        self.mrp_automation_machine.motion_control.work_offset(y=0)
        self.goto_position_abs(z=0)
        time.sleep(1)
        self.mrp_automation_machine.motion_control.wait_for_movement()
        
        #configure diverter for the destination
        # destination_lane = self.currernt_carrier.carrier_history_id.route_node_lane_dest_id
        # self.mrp_automation_machine.conveyor_1.diverter.divert(self.route_node_lane, destination_lane)
        
        #release carrier capture
        self.output_carrier_capture.value = False
        
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
        
        return True
        
    def unexpected_carrier(self, carrier_barcode):
        self._logger.warn("Unexpected Carrier barcode [%s]" % (carrier_barcode))
        api_carrier_history = self.api.env['product.carrier.history']
        #try to find existing current carrier history to update to this carriers location
        domain = [('barcode', '=', carrier_barcode), ('status','!=', 'done')]
        carrier_history_id = api_carrier_history.search(domain)
        
        #undocumented carrier, create a new carrier history object for this carrier.    
        if len(carrier_history_id) == 0:
            carrier_id = self.api.env['product.carrier'].search([('barcode','=',carrier_barcode)])
            
            #carrier not a valid carrier barcode in the database anywhere. 
            if len(carrier_id) == 0:
                _logger.error("Carrier Barcode not found in database")
                return False
                
            #create a new carrier history record for this carrier, attached to nothing.
            vals = {'carrier_id':carrier_id[0], 'sequence':0, 'route_node_id':self.route_node_lane.node_id, 'route_node_lane_id':self.route_node_lane}
            
                
            pass
        
        #update this carrier history object to this location
        
        #set current_carrier to this carrier.
        self.process_egress()
        return True
        
    def quit(self):
        super(MRP_Carrier_Lane_0, self).quit()
            
        self.output_ingress_gate.value=0
        self.output_carrier_capture.value=0
        return True
    
class MRP_Carrier_Lane_1(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane_1, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 1")
        self._logger.info("Lane INIT Complete")
        pass


class Conveyor_1(conveyor.Conveyor):
    
    def __init__(self):
        super(Conveyor_1, self).__init__(name="conveyor_1")
        
        self.pid_controller.Kp = .45
        self.pid_controller.Ki = .05
        self.pid_controller.Kd = 6
        
        self.inch_per_rpm = 4.75
        
        GPIO.setmode(GPIO.BCM)  
        GPIO.setup(5, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(5, GPIO.RISING, callback=self.tach_tick)
        
        GPIO.setup(12,GPIO.OUT)
        self.motor_p = GPIO.PWM(12,5000)
        self.motor_p.start(0)
        self.motor_duty = 40
        
        #setup diverter logic
        self.diverter = divert_1("Conveyor_1_Diverter")
        self.diverter.lane_diverter = {'work':{'work':self.diverter_work_work,'bypass':self.diverter_work_bypass},'bypass':{'work':self.diverter_bypass_work,'bypass':self.diverter_bypass_bypass}}
        pass
    
    def set_speed(self, freq_offset):
        duty = self.motor_duty + freq_offset
        
        if duty > 100:
            duty = 100
            
        if duty < 0:
            duty = 0
        
        self.motor_p.ChangeDutyCycle(duty)
        self.motor_duty = duty
        
        return super(Conveyor_1, self).set_speed(freq_offset=freq_offset)
    
    def start(self):
        self.motor_p.ChangeDutyCycle(self.motor_duty)
        return super(Conveyor_1, self).start()
    
    def stop(self):
        self.motor_p.ChangeDutyCycle(0)
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
        self.motor_p.stop()
        return super(Conveyor_1, self).quit()  
        
class divert_1(conveyor.Diverter):
    def clear_divert(self):
        time.sleep(5)
        return super(divert_1, self).clear_divert()
    

#startup this machine
if __name__ == "__main__":
    
    #odoo api settings, TODO: move these to a server_config file
    server = "usboiepxd01" 
    port = 8120
    database = "13_ESG_Beta_1-1"
    user_id = "ESG01-00181"
    password = "1q2w3e4r"
    
    #create instance of odooRPC clinet with these settings
    odoo = odoorpc.ODOO(server, port=port)
    
    #attempt a login to odoo server to init the api
    try:
        odoo.login(database, user_id, password)
    except Exception as e:
        _logger.error("Error logging in to odoo server" + e)
    
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--equipment-id', type=int, help='ODOO Maintence Equipment ID')
    args = parser.parse_args()
    
    #create instance of this test machine, and start its engine
    test_machine = TestMachine(api=odoo, asset_id=args.equipment_id)

    while True:
        time.sleep(100)
    pass