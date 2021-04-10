from odoo_automation import automation, conveyor, dispenser
import logging, time, odoorpc
import configparser, argparse
import serial
import digitalio, board, busio #blinka libs
import RPi.GPIO as GPIO #RPi libs for interupts

#setup console logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
logger=logging.getLogger("Peak Station")

class MRP_machine(automation.MRP_Automation):
    def __init__(self, api, config):
        result = super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']),config)
        
        self.current_workorder = False
        
        #setup serial barcode scanner
        self.barcode_scanner = False
        self.barcode_scanner_callback = []
        
        try:
            self.barcode_scanner = serial.Serial('/dev/ttyUSB0', baudrate=115200, rtscts=True, timeout=15)
        except Exception as e:
            logger.error(e)
            
        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self), MRP_Carrier_Lane_1(self.api, self)]
        
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
        return super(MRP_machine, self).button_start()
    
    def button_stop(self):
        return super(MRP_machine, self).button_stop()
    
    def e_stop(self):
        #put render safe i/o here.
        return super(MRP_machine, self).e_stop()
    
    def e_stop_reset(self):
        #put reboot i/o here
        return super(MRP_machine, self).e_stop_reset()

    def get_blocking_status(self):
        return super(MRP_machine, self).get_blocking_status()   

    def quit(self):
        self.barcode_scanner.close()
        return super(MRP_machine, self).quit()
        
    def get_workorders(self):
        self.current_workorder = False
        return super(MRP_machine, self).get_workorders() 
        
    def get_workorder(self, workorderID):
        self.current_workorder = self.api.env['mrp.workorder'].browse(int(workorderID))
        return super(MRP_machine, self).get_workorder(workorderID) 

class MRP_Carrier_Lane_0(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        self._logger = logging.getLogger("Carrier Lane 0")
        super(MRP_Carrier_Lane_0, self).__init__(api, mrp_automation_machine)
        self._logger.info("Lane INIT Complete")
        pass
    
    def preflight_checks(self):
        #check that the machine in front of this machine is capible of accepting more product
        return super(MRP_Carrier_Lane_0, self).preflight_checks()

    def ingress_trigger(self):
        if not self.mrp_automation_machine.current_workorder:
            return False
        return True

    def process_ingress(self):
        #clear barcode buffer
        self.mrp_automation_machine.barcode_scanner.reset_input_buffer()  
        
        #block and wait for barcode to be read
        barcode_scanned = self.mrp_automation_machine.barcode_scanner.readline()
        
        #read in the barcode data from serial port, if any.
        if not barcode_scanned:
            self._logger.info("Timeout waiting for barcode to be scanned.")
            return False
        
        #format barcode data
        barcode_scanned = barcode_scanned.decode('utf-8').replace('\r\n',"")
        
        #check the scanned barcode against the carrier thought to be next in queue    
        if barcode_scanned != self.currernt_carrier.barcode:
            #an unexpected carrier was scanned.
            self.unexpected_carrier(carrier_barcode=barcode_scanned)
            
        #if the current carrier is not already assigned to a production order, assign it to this production order.
        if not self.currernt_carrier.carrier_history_id.production_id:
            #assign carrier to work order
            self.currernt_carrier.carrier_history_id.production_id = self.mrp_automation_machine.current_workorder.production_id
            self.currernt_carrier.carrier_history_id.workorder_id = self.mrp_automation_machine.current_workorder
            self.currernt_carrier.carrier_history_id.workcenter_id = self.mrp_automation_machine.current_workorder.workcenter_id
         
        return super(MRP_Carrier_Lane_0, self).process_ingress()
    
    def process_carrier(self):
        return True #super(MRP_Carrier_Lane_0, self).process_carrier()
        
    def process_egress(self):
        #to be inherited by the main machine config and returns True when the product has processed through egress and is clear of this machine.
        self.currernt_carrier.carrier_history_id.route_node_dest_id = self.mrp_automation_machine.route_node_id
        self.currernt_carrier.carrier_history_id.route_node_lane_dest_id = self.mrp_automation_machine.route_lanes[1].route_node_lane
        return super(MRP_Carrier_Lane_0, self).process_egress()
        
    def quit(self):
        return super(MRP_Carrier_Lane_0, self).quit()
        
class MRP_Carrier_Lane_1(automation.MRP_Carrier_Lane):
    def __init__(self, api, mrp_automation_machine):
        self._logger = logging.getLogger("Carrier Lane 1")
        super(MRP_Carrier_Lane_1, self).__init__(api, mrp_automation_machine)
        self._logger.info("Lane INIT Complete")
        pass
    
    def preflight_checks(self):
        #check that the machine in front of this machine is capible of accepting more product
        return super(MRP_Carrier_Lane_1, self).preflight_checks()

    def ingress_trigger(self):
        if self.currernt_carrier:
            return True
        return False

    def process_ingress(self):
        return True
    
    def process_carrier(self):
        return True #super(MRP_Carrier_Lane_0, self).process_carrier()
        
    def process_egress(self):
        self._logger.info("Setting diverter to lane %s" % self.currernt_carrier.carrier_history_id.route_node_lane_dest_id.sequence)
        return super(MRP_Carrier_Lane_1, self).process_egress()
        
    def quit(self):
        return super(MRP_Carrier_Lane_1, self).quit()
    
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