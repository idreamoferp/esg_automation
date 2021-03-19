from odoo_automation import automation, conveyor, dispenser
import logging, time, odoorpc
import configparser, argparse

#setup console logger
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s - %(message)s",datefmt='%m/%d/%Y %I:%M:%S %p',level=logging.INFO)
logger=logging.getLogger("Peak Station")

class MRP_machine(automation.MRP_Automation):
    def __init__(self, api, config):
        result = super(MRP_machine, self).__init__(api, int(config['machine']['equipment_id']),config)

        #init route lanes
        self.route_lanes = [MRP_Carrier_Lane_0(self.api, self)]
        
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
        return super(MRP_machine, self).quit()

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
        #to be inherited by the main machine config and returns True when the product has arrived at the ingress gate.
        return super(MRP_Carrier_Lane_0, self).ingress_trigger()

    def process_ingress(self):
        #to be inherited by the main machine config and returns True when the product has processed through ingress and is ready for processing.
        return super(MRP_Carrier_Lane_0, self).process_ingress()
    
    def process_carrier(self):
        return super(MRP_Carrier_Lane_0, self).process_carrier()
        
    def process_egress(self):
        #to be inherited by the main machine config and returns True when the product has processed through egress and is clear of this machine.
        return super(MRP_Carrier_Lane_0, self).process_egress()
        
    def quit(self):
        return super(MRP_Carrier_Lane_0, self).quit()
    
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