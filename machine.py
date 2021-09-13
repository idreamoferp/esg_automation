from odoo_automation import automation, automation_web, conveyor, dispenser
import logging, time, datetime, threading, odoorpc, ast
import numpy as np
import configparser, argparse
import RPi.GPIO as GPIO 
GPIO.setmode(GPIO.BCM)
import digitalio, board, busio, neopixel
from adafruit_pca9685 import PCA9685
from adafruit_mcp230xx import mcp23017
from adafruit_ads1x15 import ads1115 
from adafruit_ads1x15 import analog_in
import simple_pid

#setup i2c devices
reset_pin = digitalio.DigitalInOut(board.D22)
reset_pin.direction = digitalio.Direction.OUTPUT
reset_pin.value = 1

_i2c_1 = busio.I2C(board.SCL, board.SDA)

_pca = PCA9685(_i2c_1)
_pca.frequency = 60

_mcp = mcp23017.MCP23017(_i2c_1)

_ads = ads1115.ADS1115(_i2c_1)
_ads.gain = 1

#setup console logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
logger=logging.getLogger("Cure Oven")

class MRP_machine(automation.MRP_Automation):
    def __init__(self, api, config):
        self.conveyor_1 = Conveyor_1("Oven Conveyor",config["conveyor_1"])
        result = super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']),config)
        
        self.logo = neopixel.NeoPixel(board.D12, 62)
        self.logo.fill((0,0,255))
        
        self.e_stop_relay = _pca.channels[15]
        self.e_stop_relay.duty_cycle = 0xffff
        
        self.heat = _pca.channels[12]
        
        
        
        # self.heat.duty_cycle = 0x0000
        
        self.fans = _pca.channels[13]
        self.fans.duty_cycle = 0x0000
        
        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self)]
        self.oven_currenttemp = 0.0
        
        self.conveyor_autostart_thread = threading.Thread(target=self.conveyor_autostart, daemon=True)
        self.conveyor_autostart_thread.start()
        
        self.pixles = neopixel.NeoPixel(board.D12, 50, brightness=1.00, pixel_order=neopixel.GRB)
        
        self.temp_0_ain = analog_in.AnalogIn(_ads, ads1115.P2)
        self.temp_1_ain = analog_in.AnalogIn(_ads, ads1115.P3)
        self.temp_0 = 0.0
        self.temp_1 = 0.0
        
        
        self.temrature_thread = threading.Thread(target=self.analog_inputs, daemon=True)
        self.temrature_thread.start()
        
        self.e_stop_relay.value = 1
        
        logger.info("Machine INIT Complete.")
        return result
        
    def read_config(self):
        self.temp_0_values = ast.literal_eval(config['machine']['temp0_value'])
        self.temp_0_temp = ast.literal_eval(config['machine']['temp0_temp'])
        self.temp_1_values = ast.literal_eval(config['machine']['temp1_value'])
        self.temp_1_temp = ast.literal_eval(config['machine']['temp1_temp'])
        
        P = float(self.config['heat_P'])
        I = float(self.config['heat_I'])
        D = float(self.config['heat_D'])
        L_limit = float(self.config['heat_L_limit'])
        U_limit = float(self.config['heat_U_limit'])
        sp = float(self.config['temp_set_point'])
        
        self.heat_pid = PID(P, I, D, setpoint=sp)
        self.heat_pid.output_limits = (L_limit, U_limit)
        
        return True
        
    @property
    def temp(self):
        #return the average of two temp sensors
        return (self.temp_0 + self.temp_1) / 2
    
    def analog_inputs(self):
        while 1:
            try:
                value_0 = self.temp_0_ain.value
                value_1 = self.temp_1_ain.value
                self.temp0 = np.interp(value_0, self.temp_0_values, self.temp_0_temp)
                self.temp1 = np.interp(value_1, self.temp_1_values, self.temp_1_temp)
                logger.info("temp 0 : %s - %s temp 1 : %s - %s delta %s" % (value_0, round(self.temp0, 1), value_1, round(self.temp1, 1), round(abs(self.temp0 - self.temp1),1)))
            except Exception as e:
                logger.error(e)
                pass
            
            time.sleep(1)
        
    def conveyor_autostart(self):
        while 1:
            run_conveyor = False
            for lane in self.route_lanes:
                if len(lane.route_node_carrier_queue) > 0:
                    run_conveyor = True
                    
                    
            if run_conveyor:
                self.conveyor_1.start()
                
            if not run_conveyor:
                self.conveyor_1.stop()
                
            time.sleep(1)
                
    def indicator_start(self, value):
        
        return super(MRP_machine, self).indicator_start(value)
    
    def indicator_warn(self, value):
        
        return super(MRP_machine, self).indicator_warn(value)
        
    def indicator_e_stop(self, value):
        
        return super(MRP_machine, self).indicator_e_stop(value)

    #Button inputs
    def button_start(self):
        #self.conveyor_1.start()
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

    def get_blocking_status(self):
        return super(MRP_machine, self).get_blocking_status()   
    
    
        
    def quit(self):
        self.conveyor_1.quit()
        self.e_stop_relay.value = False
        self.heat.value = False
        
        
        return super(MRP_machine, self).quit()

class MRP_Carrier_Lane_0(automation.MRP_Carrier_Lane):
    def timer_start(self, x):
        if not self.ingress_pin.value:
            started_one=False
            while started_one == False:
                for i in self.route_node_carrier_queue:
                    try:
                        if not self.carrier_history_cache[i].timer_start:
                            self.carrier_history_cache[i].start_timer()
                            self._logger.info("Started Timer %s at %s" % (self.carrier_history_cache[i].barcode,self.carrier_history_cache[i].timer_start))
                            started_one=True
                            break
                    except Exception as e:
                        pass
        pass
    
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 0")
        self.config =  self.mrp_automation_machine.config["lane0"]
        
        self.ingress_pin =  _mcp.get_pin(9) #digitalio.DigitalInOut(board.D14)
        self.ingress_pin.direction = digitalio.Direction.INPUT
        self.ingress_pin.pull = digitalio.Pull.UP
        # GPIO.add_event_detect(14, GPIO.FALLING, callback=self.timer_start, bouncetime=2500)
        
        self.egress_pin = _mcp.get_pin(10) #digitalio.DigitalInOut(board.D16)
        self.egress_pin.direction = digitalio.Direction.INPUT
        self.egress_pin.pull = digitalio.Pull.UP
        
        self.carrier_stop_pin = _pca.channels[10]
        self.carrier_stop_pin.duty_cycle = 0x0000
        
        #install custom carrier calss into lane
        self.carrier_class = Carrier
        
        self._logger.info("Lane INIT Complete")
        pass
    
    def preflight_checks(self):
        #check that the machine in front of this machine is capible of accepting more product
        return super(MRP_Carrier_Lane_0, self).preflight_checks()

    def ingress_trigger(self):
        #to be inherited by the main machine config and returns True when the product has arrived at the ingress gate.
        if not self.egress_pin.value:
            if len(self.route_node_carrier_queue) == 0:
                return False
            return True
            
        return super(MRP_Carrier_Lane_0, self).ingress_trigger()

    def process_ingress(self):
        #to be inherited by the main machine config and returns True when the product has processed through ingress and is ready for processing.
        
        return True
    
    def process_carrier(self):
        return super(MRP_Carrier_Lane_0, self).process_carrier()
        
    def process_egress(self):
        #to be inherited by the main machine config and returns True when the product has processed through egress and is clear of this machine
        self.carrier_stop_pin.duty_cycle = 0xffff
        time.sleep(10)
        self.carrier_stop_pin.duty_cycle = 0x0000
        return super(MRP_Carrier_Lane_0, self).process_egress()
        
    def quit(self):
        # self.pi_pwm2.ChangeDutyCycle(0)
        return super(MRP_Carrier_Lane_0, self).quit()
        
class Conveyor_1(conveyor.Conveyor):
    
    def __init__(self, name,config):
        self.config = config
        result = super(Conveyor_1,self).__init__(name)
        
        GPIO.setup(13,GPIO.OUT)
        self.pi_pwm = GPIO.PWM(13, 60)		
        self.pi_pwm.start(0)
        
        speed_pwm = self.config["speed_pwm"]
        return result
    
    def start(self):
        self.pi_pwm.ChangeDutyCycle(35)
        return super(Conveyor_1, self).start()
    
    def stop(self):
        self.pi_pwm.ChangeDutyCycle(0)
        return super(Conveyor_1, self).stop()
        
    def set_speed(self, freq_offset):
        self.pi_pwm.ChangeDutyCycle(20)
        return True
        
    def quit(self):
        self.pi_pwm.ChangeDutyCycle(0)
        return super(Conveyor_1, self).quit()
   
class Carrier(automation.Carrier):
    def __init__(self, api, mrp_automation_machine, carrier_lane):
        result = super(Carrier, self).__init__(api, mrp_automation_machine, carrier_lane)
        self.timer_start = False
        self.timer_stop = False
        self.exec_globals["time"] = time
        
        return result
        
    def start_timer(self):
        self.timer_start = time.time()
        self.logger.info("Timer started at %s " % datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
        pass
    
    def stop_timer(self):
        if self.timer_stop: 
            self.timer_stop = time.time()
            self.logger.info("Timer stopped at %s " % datetime.datetime.now().strftime("%m/%d/%Y, %H:%M:%S"))
            self.logger.info("Product soaked for %d seconds." % (self.timer_stop - self.timer_start))
        pass
    
    def timer(self, total_time):
        while time.time() - self.timer_start < total_time:
            time.sleep(1)
            
        self.stop_timer()
            
def create_odoo_api():
    #create odoo api object
    try:
        odoo = odoorpc.ODOO(config['odoo']['server_url'], port=config['odoo']['tcp_port'])
        odoo.login(config['odoo']['database'], config['odoo']['username'], config['odoo']['password'])
        logger.info("Loggedin to ODOO server %s as %s" % (config['odoo']['database'], config['odoo']['username']))
        return odoo
    except Exception as e:
        logger.error(e)
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
        logger.info("Read config file %s" % (args.c))
        return config
    except Exception as e:
        logger.error(e)
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

#Blue Board:
# Inputs:
# 1 - gpio_18
# 2 - gpio_06
# 3 - gpio_05
# 4 - gpio_23
# 5 - gpio_24
# 6 - gpio_22
# Outputs:
# 1 - gpio_12 (pwm)
# 2 - gpio_13 (pwm)
# 3 - gpio_25
# 4 - gpio_26
# 5 - gpio_27
# 6 - gpio_04

# 