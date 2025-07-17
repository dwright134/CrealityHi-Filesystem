# Support for Automatic belt tensioning module
#
# Copyright 
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import numpy as np
from .box_wrapper import BoxAction

class COM:
    def __init__(self):
        self.head = 0xf7     #帧头
        self.addr = 0x21     #设备地址
        self.len  = 3        #数据长度
        self.star = 0x00	 #状态码
        self.fun  = 0x00     #功能码
        self.data = []       #数据
        self.crc  = 0xff     #校验位
        pass

class STA:
    def __init__(self):
        self.read_version_cmd = 0      #读模块固件版本指令
        self.read_version_resp = 0     #读模块固件版本回复
        self.read_flash_cmd = 2        #读保存在flash里的变量指令
        self.read_flash_resp = 2       #读保存在flash里的变量回复
        self.write_flash_cmd = 4       #写保存在flash里的变量指令
        self.write_flash_resp = 4      #写保存在flash里的变量回复
        self.read_adc_cmd = 6          #读当前应变片ADC值指令
        self.read_adc_resp = 6         #读当前应变片ADC值回复
        self.move_slider_cmd = 8       #让滑块移动的距离指令
        self.move_slider_resp = 8      #让滑块移动的距离回复
        pass


def split_to_bytes(data):   #一个32位数据转化为4个8位数据
    # 确保输入为32位无符号整型
    data = data & 0xFFFFFFFF
    return [((data >> (8 * i)) & 0xFF) for i in range(4)][::-1]

def bytes_to_int(byte_array):    #4个8位数据转化为一个32位数据
    # 确保字节数据长度为4
    assert len(byte_array) == 4
    result = 0
    for i, byte in enumerate(byte_array):
        # 将字节左移相应的位数，并与结果进行按位或操作
        result |= (byte & 0xFF) << (8 * (3 - i))
    # 返回合并后的32位整数
    return result    




class MDL:
    def __init__(self, val):
        self.value = val             #序号
        # self.name = None             #传感器名称
        self.softversion = 0             #传感器固件版本*
        self.halversion = 0             #传感器固件版本*
        self.current_status = 0      #模块当前状态标志 ---
        self.total_place = 0         #滑块可以运动的总行程，单位 1um
        self.total_tension = 0       #应变片的总量程，单位 0.01N
        self.idl_adc = 0xfff3b6a9             #应变片空载时的 ADC 值，即 去皮/归零*
        self.full_adc = 0xffe908d8           #应变片满载时的 ADC 值，即 最大负载*
        self.current_place_adc = 0x01028304   #滑块当前应变片的 ADC 值*
        self.current_place = 0x0000       #当前滑块位置，单位 1um*
        self.current_tension = 0     #应变片当前所受拉/推力，单位 1N=
        self.target_place = 0        #滑块期望位置
        self.target_move = 0        #滑块移动距离
        self.target_tension = 0      #应变片期望受力-
        self.tension_correction_dir = 0  #应变片校准方向
        self.uart_pin = None             #但串口通信引脚
        self.convert = False             #是否更新数据
        self.read_flash = False          #是否获取flash值
        self.slope = 0                   #数据拟合参数:斜率
        self.intercept = 0               #数据拟合参数:截距
        self.mistake = 0.02               #误差范围 
        self.adjustnum1 = 140             #校准拉力值1
        self.adjustnum2 = 160            #校准拉力值2
        pass

class BELT_MDL:
    def __init__(self, config):
        self.config = config
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")

        name_parts = config.get_name().split()
        self.base_name = name_parts[0]
        self.name = name_parts[-1]

        self.mdl = {}
        self.mdl = MDL(self)
        self.com = {}
        self.com = COM()
        self.sta = {}
        self.sta = STA()
        
        self.mdl.uart_pin = config.get('ch_uart_pin')
        self.mdl.total_place = config.getint('ch_max_dis')
        self.mdl.total_tension = config.getint('ch_max_n')
        self.mdl.target_tension = config.getint('ch_best_n')
        
        self._serial = self.printer.lookup_object("serial_485 " + "serial485")
        
        
        self.ppins = self.printer.lookup_object('pins')   
        self.mdl_mcu : MCU = self.ppins.parse_pin(self.mdl.uart_pin, True, True)['chip']  
        self.oid = self.mdl_mcu.create_oid()  #声明一个id
        self.mdl_queue = self.mdl_mcu.alloc_command_queue()

        self.gcode.register_mux_command("BELT_MDL_INFO", "MDL_NAME", self.name,            #获取给定模块的详细参数，所有寄存器的值。
                                   self.cmd_BELT_MDL_INFO,desc=self.cmd_BELT_MDL_INFO_help)
        self.gcode.register_mux_command("BELT_MDL_MOVE", "MDL_NAME", self.name,            #设置模块滑块的位置
                                   self.cmd_BELT_MDL_MOVE,desc=self.cmd_BELT_MDL_MOVE_help)
        self.gcode.register_mux_command("BELT_MDL_SET", "MDL_NAME", self.name,             #设定模块推/拉力值
                                   self.cmd_BELT_MDL_SET,desc=self.cmd_BELT_MDL_SET_help)
        self.gcode.register_mux_command("BELT_MDL_CALI", "MDL_NAME", self.name,            #主要是未安装皮带着，对行程和压力进行校正
                                   self.cmd_BELT_MDL_CALI,desc=self.cmd_BELT_MDL_CALI_help)
        pass




 
    # def mdl_info_cmd_return(self):
    #     self.gcode.respond_info("mdl_info_cmd_return MDL_NAME: %s"%(self.name,))
    #     pass

    def mdl_info_cmd(self):
        self.gcode.respond_info("ACK_mdl_info")
        self.Get_version()
        self.get_flash_data()
        self.init_adc_to_num()
        self.get_adc()
        self.adc_to_num(self.mdl.current_place_adc)

        # reactor = self.printer.get_reactor()
        # self.gcode.respond_info("reactor: %s"%(reactor,))
        # self.gcode.respond_info("reactor1: %s"%(reactor.monotonic(),))
        # reactor.pause(reactor.monotonic() + 10.0)
        # self.gcode.respond_info("reactor2: %s"%(reactor,))
        # self.gcode.respond_info("reactor3: %s"%(reactor.monotonic(),))
        # self.get_flash_data()
        # self.init_adc_to_num()
        # self.get_adc()
        # self.adc_to_num(self.mdl.current_place_adc)
        # self.mdl_info.send([self.oid])
        # self.Get_version()
        # self.get_flash_data()
        # self.get_adc()
        # self.set_move(1,0x11223344)
        # self.write_flash()
        # mdl_info_buf = self.mdl_info.send([self.oid])
        # self.gcode.respond_info("ACK_mdl_info: %s"%str(mdl_info_buf))
        pass

    def set_place(self):         #设置滑块绝对位置
        self.gcode.respond_info("ACK_mdl_pos")
        if((self.mdl.current_place==0xffffffff)|(self.mdl.idl_adc==0xffffffff)|(self.mdl.full_adc==0xffffffff)):
                raise self.printer.command_error("""{"code":"key710", "msg":"Belt tension module strain gauge not calibrated abnormal: '%s' set_place_error", "values": []}"""% (self.name))
        self.target_move = self.target_place - self.mdl.current_place
        self.mdl.current_place = self.target_place
        movedir = 1 if self.target_move>0 else 0
        movenum = abs(self.target_move)
        self.set_move(movedir,movenum)
        self.write_flash()
        # mdl_pos_buf = self.mdl_pos.send([self.oid, 0])
        # self.gcode.respond_info("ACK_mdl_pos: %s"%str(mdl_pos_buf))
        pass

    def set_tension(self):
        self.init_adc_to_num()
        self.get_adc()
        self.adc_to_num(self.mdl.current_place_adc)
        movetimes = 0
        while(1):
            movetimes += 1 
            self.gcode.respond_info("times:%s"%movetimes)
            if(movetimes > 99):
                self.gcode.respond_info("ACK_mdl_pos error! timesout")
                break
            aimpull = self.target_tension - self.mdl.current_tension   #获得拉力期望差距值
            aimpull = abs(aimpull)                                     #取绝对值
            aimpull = 10 if aimpull > 10 else aimpull                  #限幅
            aimmove = int(aimpull*aimpull) + 2                         #非线性算法，使得差距大时运动行程大，差距小时运动行程小
            if(aimmove > movetimes):                                   #位移行程随调节次数衰减，避免丝杆非线性导致的震荡，强行收敛
                aimmove = aimmove - movetimes                          #根据调节次数强行衰减位移量，提高精度
            if(movetimes > 50):                                        #前50次不能调整成功，说明出现丝杆非线性导致的震荡
                aimmove = 2                                            #以最小步数进行微调，以抵抗非线性带来的震荡
            if(self.target_tension*(1+self.mdl.mistake) <  self.mdl.current_tension):
                self.set_move(0,aimmove)
                self.mdl.current_place = self.mdl.current_place - aimmove
                self.get_adc()
                self.adc_to_num(self.mdl.current_place_adc)
            elif(self.target_tension*(1-self.mdl.mistake) >  self.mdl.current_tension):
                self.set_move(1,aimmove)
                self.mdl.current_place = self.mdl.current_place + aimmove
                self.get_adc()
                self.adc_to_num(self.mdl.current_place_adc)
            else:
                self.gcode.respond_info("ACK_mdl_pos success!")
                break   
        self.write_flash()
        # mdl_ten_buf = self.mdl_ten.send([self.oid, 1])
        # self.gcode.respond_info("ACK_mdl_ten: %s"%str(mdl_ten_buf))
        pass

    def set_tension_correction(self):
        if(self.tension_correction_dir==0):
            self.mdl.current_place = 0 
            self.write_flash()
        elif(self.tension_correction_dir==1):
            self.mdl.adjustnum1 = self.tension_correction_ten
            self.get_adc()
            self.mdl.idl_adc = self.mdl.current_place_adc
            self.write_flash()
        elif(self.tension_correction_dir==2):
            self.mdl.adjustnum2 = self.tension_correction_ten
            self.get_adc()
            self.mdl.full_adc = self.mdl.current_place_adc
            self.write_flash()
        
            # self.get_flash_data()
        
        # mdl_init_buf = self.mdl_init.send([self.oid, self.tension_correction_dir])
        # self.gcode.respond_info("ACK_mdl_init: %s"%str(mdl_init_buf))
        pass

    cmd_BELT_MDL_INFO_help = "obtain detailed parameters for the given module"
    def cmd_BELT_MDL_INFO(self, gcmd):  
        self.config_addr()   
        self.mdl_info_cmd()
        self.gcode.respond_info("MDL_NAME: %s"%(self.name,))
        pass
    
    cmd_BELT_MDL_MOVE_help = "set the position of the module slider."
    def cmd_BELT_MDL_MOVE(self, gcmd):
        self.config_addr() 
        self.target_place= gcmd.get_int('POS', 0)
        self.set_place()
        self.gcode.respond_info("MDL_NAME: %s"%(self.name,))
        pass

    cmd_BELT_MDL_SET_help = "set the module tension value."
    def cmd_BELT_MDL_SET(self, gcmd):
        self.config_addr() 
        self.target_tension= gcmd.get_int('MDL_N', 140.0)
        self.set_tension()
        self.gcode.respond_info("MDL_NAME: %s"%(self.name,))
        pass

    cmd_BELT_MDL_CALI_help = "calibrate stroke and pressure."
    def cmd_BELT_MDL_CALI(self, gcmd):
        self.config_addr() 
        self.tension_correction_dir= gcmd.get_int('DIR', 0)
        self.tension_correction_ten= gcmd.get_int('TEN', None)
        self.set_tension_correction()
        self.gcode.respond_info("MDL_NAME: %s"%(self.name,))
        pass

    def Get_version(self):                   #获取版本号
        sendbuf = self.send_sensor_data(self.sta.read_version_cmd,[])
        self.gcode.respond_info("sendbuf: %s"%sendbuf)
        uartbuf = self.send_data(sendbuf) 
        self.gcode.respond_info("resetbuf: %s"%uartbuf)
        redata = self.recv_sensor_data(uartbuf)
        if(redata[0] == 0):
            self.gcode.respond_info("reset:start error")
            return redata
        if(redata[1] != self.sta.read_version_resp):   #校验功能码
            self.gcode.respond_info("reset:comfun error")
            redata = 0,-5,0
            return redata
        if(redata[1] == self.sta.read_version_resp):   #功能码正常
            self.mdl.halversion  = redata[2][:2]    #硬件版本号
            self.mdl.softversion = redata[2][2:]    #软件版本号
            self.gcode.respond_info("halversion:%s"%self.mdl.halversion)
            self.gcode.respond_info("softversion:%s"%self.mdl.softversion)
        pass

    def Get_flash(self,flash_num):                   #获取flash信息
        sendbuf = self.send_sensor_data(self.sta.read_flash_cmd,[flash_num])
        self.gcode.respond_info("sendbuf: %s"%sendbuf)
        uartbuf = self.send_data(sendbuf)
        self.gcode.respond_info("resetbuf: %s"%uartbuf)
        redata = self.recv_sensor_data(uartbuf)
        if(redata[0] == 0):
            self.gcode.respond_info("reset:start error")
            return redata
        if(redata[1] != self.sta.read_flash_resp):   #校验功能码
            self.gcode.respond_info("reset:comfun error")
            redata = 0,-5,0
            return redata
        if(redata[1] == self.sta.read_flash_resp):   #功能码正常
            # print("redata",redata)
            return redata
        pass

    def get_flash_data(self):                 
        flash_buf = self.Get_flash(3)
        # self.gcode.respond_info("flash_data:%s"%flash_buf[2])
        if(flash_buf[0] == 0):   #数据异常
            return None
        if(flash_buf[0] == 1):
            flash_data_num = flash_buf[2][0]  #获取数据长度
            flash_data0 = flash_buf[2][1:5]   #获取数据4位一组
            flash_data1 = flash_buf[2][5:9]
            flash_data2 = flash_buf[2][9:13]
            # self.gcode.respond_info("flash_data_num:%s"%flash_data_num)
            # self.gcode.respond_info("flash_data0:%s"%flash_data0)
            # self.gcode.respond_info("flash_data1:%s"%flash_data1)
            # self.gcode.respond_info("flash_data2:%s"%flash_data2)
            flash_data_num0 = bytes_to_int(flash_data0)   #把4位一组的数据转换为32位的数值
            flash_data_num1 = bytes_to_int(flash_data1)
            flash_data_num2 = bytes_to_int(flash_data2)
            # self.gcode.respond_info("flash_data_num0:%s"%flash_data_num0)
            # self.gcode.respond_info("flash_data_num1:%s"%flash_data_num1)
            # self.gcode.respond_info("flash_data_num2:%s"%flash_data_num2)
            self.mdl.current_place = flash_data_num0       #当前滑块位置，单位 0.01mm*
            self.mdl.idl_adc = flash_data_num1             #应变片空载时的 ADC 值，即 去皮/归零*
            self.mdl.full_adc = flash_data_num2            #应变片满载时的 ADC 值，即 最大负载*
            self.gcode.respond_info("current_place:%s"%self.mdl.current_place)
            self.gcode.respond_info("idl_adc:%s"%self.mdl.idl_adc)
            self.gcode.respond_info("full_adc:%s"%self.mdl.full_adc)
            if((self.mdl.current_place==0xffffffff)|(self.mdl.idl_adc==0xffffffff)|(self.mdl.full_adc==0xffffffff)):
                raise self.printer.command_error("""{"code":"key710", "msg":"Belt tension module strain gauge not calibrated abnormal: '%s'", "values": []}"""% (self.name))
        pass

    def write_flash_buf(self,flash_num,flash_data):   #写入flash信息，写入数据数量+数据内容
        flash_data_buf = [flash_num]
        flash_data_buf.extend(flash_data)
        sendbuf = self.send_sensor_data(self.sta.write_flash_cmd,flash_data_buf)
        self.gcode.respond_info("sendbuf: %s"%sendbuf)
        uartbuf = self.send_data(sendbuf)
        self.gcode.respond_info("resetbuf: %s"%uartbuf)
        redata = self.recv_sensor_data(uartbuf)
        if(redata[0] == 0):
            self.gcode.respond_info("reset:start error")
            return redata
        if(redata[1] != self.sta.write_flash_resp):    #校验功能码
            self.gcode.respond_info("reset:comfun error")
            redata = 0,-5,0
            return redata
        if(redata[1] == self.sta.write_flash_resp):    #功能码正常
            # print("redata",redata)
            return redata
        pass   

    def write_flash(self):               #写入flash信息
        data0 = self.mdl.current_place       #当前滑块位置，单位 0.01mm*
        data1 = self.mdl.idl_adc             #应变片空载时的 ADC 值，即 去皮/归零*
        data2 = self.mdl.full_adc            #应变片满载时的 ADC 值，即 最大负载*
        # data0 = 0x01020304
        # data1 = 0x11223344
        # data2 = 0x04030201
        # self.gcode.respond_info("write_data0:%s"%data0)
        # self.gcode.respond_info("write_data1:%s"%data1)
        # self.gcode.respond_info("write_data2:%s"%data2)
        buf_data0 = split_to_bytes(data0)   #把32位的数值转换成4个8位的数据
        buf_data1 = split_to_bytes(data1)   
        buf_data2 = split_to_bytes(data2)
        # self.gcode.respond_info("buf_data0:%s"%buf_data0)
        # self.gcode.respond_info("buf_data1:%s"%buf_data1)
        # self.gcode.respond_info("buf_data2:%s"%buf_data2)
        data_buf = buf_data0                #把数据合成一个列表
        data_buf.extend(buf_data1)
        data_buf.extend(buf_data2)
        flash_buf = self.write_flash_buf(3,data_buf)   #发送3个数据
        self.gcode.respond_info("flash_data:%s"%flash_buf[2])
        if(flash_buf[0] == 0):    #校验返回的数据是否正常
            return None
        if(flash_buf[0] == 1):
            flash_data_num = flash_buf[2][0]   #数据长度
            flash_data0 = flash_buf[2][1:5]    #数据内容
            flash_data1 = flash_buf[2][5:9]
            flash_data2 = flash_buf[2][9:13]
            # self.gcode.respond_info("flash_data_num:%s"%flash_data_num)
            # self.gcode.respond_info("flash_data0:%s"%flash_data0)
            # self.gcode.respond_info("flash_data1:%s"%flash_data1)
            # self.gcode.respond_info("flash_data2:%s"%flash_data2)
            flash_data_num0 = bytes_to_int(flash_data0)     #把数据由4个8位数据转换位32位数值
            flash_data_num1 = bytes_to_int(flash_data1)
            flash_data_num2 = bytes_to_int(flash_data2)
            # self.gcode.respond_info("flash_data_num0:%s"%flash_data_num0)
            # self.gcode.respond_info("flash_data_num1:%s"%flash_data_num1)
            # self.gcode.respond_info("flash_data_num2:%s"%flash_data_num2)
            if((self.mdl.current_place == flash_data_num0)|(self.mdl.idl_adc == flash_data_num1)|(self.mdl.full_adc == flash_data_num2)): 
                return 1     #flash写入成功，写读数据一致
            else:
                return -1    #flash写入失败，写读数据不一致
            self.gcode.respond_info("current_place:%s"%flash_data_num0)
            self.gcode.respond_info("idl_adc:%s"%flash_data_num1)
            self.gcode.respond_info("full_adc:%s"%flash_data_num2)
        pass 

    def get_adc_buf(self):                       #获取ADC数据
        sendbuf = self.send_sensor_data(self.sta.read_adc_cmd,[])         
        self.gcode.respond_info("sendbuf: %s"%sendbuf)
        uartbuf = self.send_data(sendbuf)
        self.gcode.respond_info("resetbuf: %s"%uartbuf)
        redata = self.recv_sensor_data(uartbuf)
        if(redata[0] == 0):
            self.gcode.respond_info("reset:start error")
            return redata
        if(redata[1] != self.sta.read_adc_resp):     #校验功能码
            self.gcode.respond_info("reset:comfun error")
            redata = 0,-5,0
            return redata
        if(redata[1] == self.sta.read_adc_resp):     #功能码正常
            # self.gcode.respond_info("redata:%s"%redata[2])
            return redata
        pass 

    def get_adc(self):                       #获取ADC值
        adc_buf = self.get_adc_buf()
        self.gcode.respond_info("adc_buf:%s"%adc_buf[2])
        if(adc_buf[0] == 0):   #校验返回的数据是否正常
            return None 
        if(adc_buf[0]==1):
            adc_num = bytes_to_int(adc_buf[2])
            self.mdl.current_place_adc = adc_num   #滑块当前位置应变片的 ADC 值*
            self.gcode.respond_info("adc_num:%s"%adc_num)
            return adc_num
        pass 

    def set_move_buf(self,dir,rang_buf):                   #滑块移动，传入方向+数据
        set_move_buf = [dir]
        set_move_buf.extend(rang_buf)
        sendbuf = self.send_sensor_data(self.sta.move_slider_cmd,set_move_buf)
        self.gcode.respond_info("sendbuf: %s"%sendbuf)
        uartbuf = self.send_data(sendbuf)
        self.gcode.respond_info("resetbuf: %s"%uartbuf)
        redata = self.recv_sensor_data(uartbuf)
        if(redata[0] == 0):
            self.gcode.respond_info("reset:start error")
            return redata
        if(redata[1] != self.sta.move_slider_resp):     #校验功能码
            self.gcode.respond_info("reset:comfun error")
            redata = 0,-5,0 
            return redata
        if(redata[1] == self.sta.move_slider_resp):
            # print("redata",redata)
            return redata
        pass 
    
    def set_move(self,dir,rang_num):           #滑块移动 传入方向+数值
        if((rang_num >= 0)&(rang_num < 0xffff)):
            rang_buf = []
            rang_buf = split_to_bytes(rang_num)    #把32位数值转换为4个8位的数据
            move_buf = self.set_move_buf(dir,rang_buf)
            delaytime = rang_num * 0.0132
            # delaytime = int(delaytime)
            reactor = self.printer.get_reactor()
            reactor.pause(reactor.monotonic() + delaytime)
            self.gcode.respond_info("move_buf:%s"%move_buf[2])
            if(move_buf[0] == 0):   #校验返回的数据是否正常
                return None 
            if(move_buf[0]==1):
                move_num_buf = move_buf[2][1:]
                move_num = bytes_to_int(move_num_buf)
                self.gcode.respond_info("move_num:%s"%move_num)
                self.gcode.respond_info("current_place:%s"%self.mdl.current_place)
                return move_num
        else:
            self.gcode.respond_info("move_num error:%s"%move_num)
        pass 

    def init_adc_to_num(self):    #根据现有的参数对adc和拉力做数据拟合
        if((self.mdl.current_place==0xffffffff)|(self.mdl.idl_adc==0xffffffff)|(self.mdl.full_adc==0xffffffff)):
                raise self.printer.command_error("""{"code":"key710", "msg":"Belt tension module strain gauge not calibrated abnormal: '%s'adc_to_num_error", "values": []}"""% (self.name))
        xd = [self.mdl.idl_adc,self.mdl.full_adc]
        yd = [self.mdl.adjustnum1,self.mdl.adjustnum2]
        xn = np.array(xd)
        yn = np.array(yd)
        # 使用numpy的polyfit函数进行线性拟合
        # polyfit的第三个参数是多项式的度数，这里设置为1表示线性拟合
        coefficients = np.polyfit(xn, yn, 1)
        slope, intercept = coefficients
        self.mdl.slope = slope
        self.mdl.intercept = intercept
        self.gcode.respond_info("slope:%s"%slope)
        self.gcode.respond_info("intercept:%s"%intercept)
        pass

    def adc_to_num(self,adc_data):     #在完成初始化后，输入adc值返回对应的拉力
        if((self.mdl.slope == 0)&(self.mdl.intercept == 0)):
            return None   #error ADC parameters must be initialized first
        adc_num = adc_data * self.mdl.slope + self.mdl.intercept
        self.mdl.current_tension = adc_num
        self.gcode.respond_info("pull_num:%s"%adc_num)
        return adc_num
        pass
    
    def config_addr(self):
        self.com.addr = 0x22 if self.name == 'mdly' else 0x21
        pass

        

    def send_sensor_data(self,sen_fun,sen_data):   #组包485协议数据包 ，传入两个参数1：功能码，2：需要发送的数据
        # com = COM()
        self.com.len  = len(sen_data)+3
        self.com.data = sen_data
        self.com.fun  = sen_fun
        self.com.crc  = 0
        combuf = []
        combuf.append(self.com.head)    #数据头
        combuf.append(self.com.addr)    #数据地址
        combuf.append(self.com.len)     #数据长度
        combuf.append(self.com.star)    #状态码
        combuf.append(self.com.fun)     #功能码
        combuf.extend(self.com.data)    #需要发送的数据
        combuf.append(self.com.crc)     #crc校验
        return combuf
        pass

    def recv_sensor_data(self,rec_data):    #接收数据解码函数
        # com = COM()
        if(rec_data == None):          #判断接收数据是否为空
            self.gcode.respond_info("reset:resetbuf is None")
            raise self.printer.command_error("""{"code":"key710", "msg":"Communication abnormality of belt automatic tensioning module 485: '%s'", "values": []}"""% (self.name))
            #通信数据为空，异常报错，结束当前指令，提示异常模块
            return 0,-1,0
        if(len(rec_data)<3):           #判断数据长度是否正常
            self.gcode.respond_info("reset: <3")
            return 0,-2,0
        if(rec_data[0] != self.com.head):   #判断数据头是否正常
            self.gcode.respond_info("reset: head error")
            return 0,-3,0
        if(rec_data[1] != self.com.addr):   #判断数据地址是否正常
            self.gcode.respond_info("reset: head error")
            return 0,-4,0
        leng = rec_data[2]             #获取数据长度
        # print("leng",leng)
        sen_fun = rec_data[4]          #获取功能码
        sen_data = rec_data[5:leng-3+5]  #获取接收的数据
        return 1,sen_fun,sen_data      #返回的数据[0]0为异常1为正常，[1]负数为异常值，正数为功能码，[2]数据
        pass

    def send_data(self,hex_data):
        hexsendbuf = hex_data[1:-1]
        readbuf = self._serial.cmd_send_data_with_response(hexsendbuf, 1)
        return readbuf

    def get_status(self, eventime):
        return dict(tension=self.mdl.current_tension)

def load_config(config):      #一个模块的初始化入口
    prt = BELT_MDL(config)
    # config.get_printer().add_object('probe', probe.PrinterProbe(config, prt))
    return prt

def load_config_prefix(config):    #多个模块的初始化入口
    prt = BELT_MDL(config)
    # config.get_printer().add_object('probe', probe.PrinterProbe(config, prt))
    return prt




 










