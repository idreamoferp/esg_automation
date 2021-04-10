from odoo_automation import automation, automation_web, conveyor, dispenser
import logging, time, odoorpc
import configparser, argparse
import RPi.GPIO as GPIO 
GPIO.setmode(GPIO.BCM)
import digitalio, board

#setup console logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
logger=logging.getLogger("Peak Station")

class MRP_machine(automation.MRP_Automation):
    def __init__(self, api, config):
        self.conveyor_1 = Conveyor_1("Oven Conveyor",config["conveyor_1"])
        result = super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']),config)

        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self)]
        self.oven_currenttemp = 0.0
        
        
        logger.info("Machine INIT Complete.")
        return result
    
    def indicator_start(self, value):
        
        return super(MRP_machine, self).indicator_start(value)
    
    def indicator_warn(self, value):
        
        return super(MRP_machine, self).indicator_warn(value)
        
    def indicator_e_stop(self, value):
        
        return super(MRP_machine, self).indicator_e_stop(value)

    #Button inputs
    def button_start(self):
        self.conveyor_1.start()
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
        return super(MRP_machine, self).quit()

class MRP_Carrier_Lane_0(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        self._logger = logging.getLogger("Carrier Lane 0")
        self.config =  self.mrp_automation_machine.config["lane0"]
        
        self.ingress_pin = digitalio.DigitalInOut(board.D14)
        self.ingress_pin.direction = digitalio.Direction.INPUT
        self.ingress_pin.pull = digitalio.Pull.UP
        
        self.egress_pin = digitalio.DigitalInOut(board.D16)
        self.egress_pin.direction = digitalio.Direction.INPUT
        self.egress_pin.pull = digitalio.Pull.UP
        
        self.carrier_stop_pin = digitalio.DigitalInOut(board.D25)
        self.carrier_stop_pin.direction = digitalio.Direction.OUTPUT
        self.carrier_stop_pin.value = 0
        
        GPIO.setup(int(self.config["pwm_pin2"]),GPIO.OUT)
        self.pi_pwm2 = GPIO.PWM(int(self.config["pwm_pin2"]),int(self.config["pwm_freq2"]))		
        self.pi_pwm2.start(0)
        
        #install custom carrier calss into lane
        self.carrier_class = Carrier
        
        self._logger.info("Lane INIT Complete")
        pass
    
    def preflight_checks(self):
        #check that the machine in front of this machine is capible of accepting more product
        return super(MRP_Carrier_Lane_0, self).preflight_checks()

    def ingress_trigger(self):
        #to be inherited by the main machine config and returns True when the product has arrived at the ingress gate.
        # if self.ingress_pin.value == False:
        #     self._logger.info("Pallet Detected")
        #     return super(MRP_Carrier_Lane_0, self).ingress_trigger()
            
        return False

    def process_ingress(self):
        #to be inherited by the main machine config and returns True when the product has processed through ingress and is ready for processing.
        
        return super(MRP_Carrier_Lane_0, self).process_ingress()
    
    def process_carrier(self):
        return super(MRP_Carrier_Lane_0, self).process_carrier()
        
    def process_egress(self):
        #to be inherited by the main machine config and returns True when the product has processed through egress and is clear of this machine.
        self.pi_pwm2.ChangeDutyCycle(10)
        if self.carrier_stop_pin.value == True:
            return True
            
        return super(MRP_Carrier_Lane_0, self).process_egress()
        
    def quit(self):
        self.pi_pwm2.ChangeDutyCycle(0)
        return super(MRP_Carrier_Lane_0, self).quit()
        
class Conveyor_1(conveyor.Conveyor):
    
    def __init__(self, name,config):
        self.config = config
        result = super(Conveyor_1,self).__init__(name)
        GPIO.setup(int(self.config["pwm_pin"]),GPIO.OUT)
        self.pi_pwm = GPIO.PWM(int(self.config["pwm_pin"]),int(self.config["pwm_freq"]))		
        self.pi_pwm.start(0)
        speed_pwm = self.config["speed_pwm"]
        return result
        
    def set_speed(self, freq_offset):
        self.pi_pwm.ChangeDutyCycle(20)
        return True
        
    def quit(self):
        self.pi_pwm.ChangeDutyCycle(0)
        return super(Conveyor_1, self).quit()
   
class Carrier(automation.Carrier):
    def __init__(self, api, mrp_automation_machine, carrier_lane):
        return super(Carrier, self).__init__(api, mrp_automation_machine, carrier_lane)
        
        
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
    machine.button_start()
    
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

