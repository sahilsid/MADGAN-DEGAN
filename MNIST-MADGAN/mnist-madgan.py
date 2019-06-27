import argparse, sys
import os
import random
import torch
import torch.nn as nn
import torch.nn.parallel
import torch.backends.cudnn as cudnn
import torch.optim as optim
import torch.utils.data
import torch.datasets as dset
import torch.utils as vutils
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import torch.distributions as dist
import warnings

import MNISTDiscriminator, MNISTSharedGenerator, MNISTUnsharedGenerator
import Optim
import utils
from Logger import Logger
import Losses

from datetime import date

from mnist_madgan_params import ARGS #import the paramters file



#add the command line arguments
parser = argparse.ArgumentParser()

parser.add_argument('--epochs', help='Number of epochs to run. Default=30', default=30, type =int)
parser.add_argument('--gpu', help='Use 0 for CPU and 1 for GPU. Default=1', default=1, type =int)
parser.add_argument('--num_channels', help='Number of channels in the real images in the real image dataset. Default=1', default=1, type=int)
parser.add_argument('--image_size', help='The size to which the input images will be resized. Default=32', default=32, type=int)
parser.add_argument('--leaky_slope', help='The negative slope of the Leaky ReLU activation used in the architecture. Default=0.2', default=0.2, type=float)
parser.add_argument('--dataroot', help='The parent dir of the dir(s) that contain the data. Default=\'./data\'', default='./data', type =str),
parser.add_argument('--n_z', help='The size of the noise vector to be fed to the generator. Default=100', default=100, type=int)
parser.add_argument('--batch_size', help='The batch size to be used while training. Default=120', default=120, type=int)
parser.add_argument('--num_generators', help='Number of generators to use. Default=3', default=3, type=int)
parser.add_argument('--degan', help ='1 if want to use modified loss function otherwise 0. Default=0', default=0, type=bool)
parser.add_argument('--sharing', help='1 if you want to use the shared generator. 0 otherwise. Default=0', default=0, type=bool)
parser.add_argument('--gpu_add', help='Address of the GPU you want to use. Default=0', default=0, type=int)
parser.add_argument('--lrg', help='Learning rate for the generator', default=1e-4, type=float)
parser.add_argument('--lrd', help='Learning rate for the discriminator', default=1e-4, type=float)
parser.add_argument('--bt1', help='Beta 1 parameter of the Adam Optimizer. Default=0.5', default=0.5, type=float)
parser.add_argument('--bt2', help='Beta 2 parameter of the Adam Optimizer. Default=0.999', default=0.999, type=float)
parser.add_argument('--ni', help='Noise degaradation interval. Default=1000', default=1000, type=int)
parser.add_argument('--ndf', help='Noise degradation factor. Default=0.98', default=0.98, type=float)
parser.add_argument('--nd', help='Noise standard dev. Default=0.1', default=0.98, type=float)



# parser.add_argument('--out_dir', help='The directory where the output will be stored. Give the relative path')
"""
The params defined by the command line args
"""
################################
num_epochs = args.epochs
is_gpu = args.gpu
num_channels = args.num_channels
image_size = args.image_size
leaky_slope = args.leaky_slope
dataroot = args.dataroot
n_z = args.n_z
batch_size = args.batch_size
num_generators = args.num_generators
is_degan = args.degan
is_sharing = args.sharing
gpu_add = args.gpu_add
lrd = args.lrd
lrg = args.lrg
beta1 = args.bt1
beta2 = args.bt2
NOISE_INTERVAL=args.ni
NOISE_DEGRADATION_FACTOR=args.ndf
NOISE_DEV=args.nd



CWD = os.getcwd()
SUB_DIR = 'degan-MNIST-'+str(is_degan)+'epc='+str(num_epochs)+'sharing'+str(is_sharing)+'lrd='+str(lrd)+'lrg'+str(lrg)
SAVE_DIR = str(cwd)+SUB_DIR

#Init the Logger defined in Logger.py
logger = Logger(SAVE_DIR+'/log.txt')

device = torch.device("cuda:"+str(gpu_add) if (torch.cuda.is_available() and num_gpu > 0) else "cpu")
################################

"""
This section is for raising warnings/exceptions related to the command line args
"""
############################################################################################
if(is_gpu>1 or is_gpu<0):
    raise ValueError("gpu arg is either one or zero. You entered {}".format(is_gpu))
if(num_channels<=0):
    raise ValueError("num_channels has to be greater than 0. You entered {}".format(num_channels))
if(image_size<=0):
    raise ValueError("image_size has to be greater than 0. You entered {}".format(image_size))
if(leaky_slope<0.5):
    warnings.warn("the negative slope argument of the LeakyReLU activation is unusually low. You entered {}".format(leaky_slope))
if(os.ispath.isdir(dataroot)==False):
    raise FileNotFoundError("the path specified in dataroot is not valid. You entered {}".format(dataroot))
if(n_z<64):
    warnings.warn("The length of the noise vector is unusually low. You entered {}".format(n_z))
if(batch_size<=0):
    raise ValueError("Invalid batch size. Has to be greater than zero. You entered {}".format(batch_size))
if(num_generators<=0):
    raise ValueError("Invalid number of generators. Has to be greater than zero. You entered {}".format(num_generators))
if(is_degan<=0 or is_degan>1):
    raise ValueError("degan parameter is either zero or one. You entered {}".format(is_degan))
if(is_sharing<=0 or is_sharing>1):
    raise ValueError("sharing parameter is either zero or one. You entered {}".format(is_sharing))
###################################################################################################



"""
This section deals with loading the data
"""
################################
#Function which returns the dataloader
def get_dataloader():
    dataset = dset.ImageFolder(root=dataroot,transform=transforms.Compose([
                                transforms.Resize(image_size),
                                transforms.ToTensor(),
                                transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
                            ]))
    # Create the dataloader
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=batch_size, shuffle=True, num_workers=workers)

    return dataloader
################################


"""
Initialize the weights in this cell
"""
################################
def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        nn.init.normal_(m.weight.data, ARGS.conv_weights_init_mean, ARGS.conv_weights_init_dev)
    elif classname.find('BatchNorm') != -1:
        nn.init.normal_(m.weight.data, ARGS.bn_weights_init_mean, ARGS.bn_weights_init_dev)
        nn.init.constant_(m.bias.data, ARGS.bn_bias_weights_init)
################################

"""
Initialize the generator and the discriminator and dataloader
"""
##########################################
dataloader = get_dataloader()

if is_sharing==False:
    generator = MNISTUnsharedGenerator(num_generators, n_z, leaky_slope, batch_size).to(device)
else:
    generator = MNISTSharedGenerator(num_generators, n_z, leaky_slope, batch_size).to(device)

generator.apply(weights_init)

discriminator = MNISTDiscriminator(num_generators, num_channels, leaky_slope)
discriminator.apply(weights_init)
##########################################

"""
Init the optimizers for the generator and the discriminator and the losses
"""
##########
loss = nn.CrossEntropyLoss()


optimD = Optim.get_adam(discriminator.parameters(), beta1 = beta1, beta2=beta2)
optimG = Optim.get_adam(generator.parameters(), beta1 = beta1, beta2=beta2)
##########

"""
Create the directories for storing the results
"""
######################
os.mkdir(SAVE_DIR)
os.mkdir(SAVE_DIR+'/Results')

######################


"""
Init the loss lists for G and D
"""
#########
D_losses = []
G_losses = []
#########

iters=0

num_batches = len(dataloader)

DEBUG=True

for epoch in range(num_epochs):
    for i, data in enumerate(dataloader, 0):

        ############################################
        #Train the discriminator first
        ############################################

        discriminator.zero_grad()
        #1. Train D on real data
        #fetch natch of real images
        real_images_batch = data[0].to(device)
        real_b_size = real_images_batch.size(0)

        if real_b_size!=batch_size:
            continue

        #generate labels for the real batch of data...the (k+1)th element is 1...rest are zero
        D_label_real  = get_labels(num_generators, -1, real_b_size, device)

        #forward pass for the real batch of data and then resize  
        
        gen_input_noise = generate_noise_for_generator(real_b_size//num_generators, n_z, device)
        gen_output = generator(gen_input_noise)#, real_b_size//num_generators)
        
        gen_out_d_in = gen_output.detach()
        ##############################################################
        norm = dist.Normal(torch.tensor([0.0]), torch.tensor([NOISE_DEV]))
        
        x_noise = norm.sample(gen_out_d_in.size()).view(gen_out_d_in.size()).to(device)
        gen_out_d_in = gen_out_d_in + x_noise 
        
        #################################################################
        D_labels_for_zero = get_labels(num_generators, 0, real_b_size//num_generators, device)
        D_labels_for_one = get_labels(num_generators, 1, real_b_size//num_generators, device)
        D_labels_for_two = get_labels(num_generators, 2, real_b_size//num_generators,  device)

        D_Label_Fake = torch.cat([D_labels_for_zero, D_labels_for_one, D_labels_for_two])
        D_Labels = torch.cat([D_label_real, D_Label_Fake])
        
        D_output_real = discriminator(real_images_batch).view((real_b_size,-1))
        D_Fake_Output = discriminator(gen_out_d_in).view((real_b_size, -1))

        D_Output = torch.cat([D_output_real, D_Fake_Output])
        
        if iters%NOISE_INTERVAL==0:
            NOISE_DEV=NOISE_DEV*NOISE_DEGRADATION_FACTOR
            # print("NOISE DEV IS NOW :{}".format(NOISE_DEV))
            logger.log("NOISE DEV IS NOW :{}".format(NOISE_DEV))

        # if DEBUG:
        #     print("Real Images Batch Size: {} and gen Output Size: {}".format(real_images_batch.size(), gen_output.size()))

    

#             D_Output = torch.cat([D_output_real, D_Fake_Output])

#             if DEBUG:
#                 print(D_Fake_Output.size(), D_Output.size(), D_Labels.size())
        if is_degan:
            err_D = Losses.D_Loss(D_Fake_Output, D_output_real, D_Label_Fake, loss)
        else:
            err_D = loss(D_Output, D_Labels)


        err_D.backward(retain_graph=True)

        optimD.step()

        ########################################
        #Train the generators
        ########################################

        generator.zero_grad()


        D_Fake_Output_G = discriminator(gen_output+x_noise).view((real_b_size, -1))

        G_Labels = get_labels(num_generators, -1, D_Fake_Output_G.size(0),  device)

        if is_degan:
            err_G = G_Loss(D_Fake_Output_G, D_output_real, D_Label_Fake, loss)
        else:
            err_G = loss(D_Fake_Output_G, G_Labels)


        err_G.backward()

        optimG.step()


        #print to keep track of training

        if iters%CHECK_INTERVAL==0:
            logger.log("Iters: {}; Epo: {}/{}; Btch: {}/{}; D_Err: {}; G_Err: {};".format(iters, epoch, num_epochs, i,num_batches,  err_D.item(), err_G.item()))


        #add to the dicts for keeping track of losses
        D_losses.append(err_D.item())
        G_losses.append(err_G.item())



        if (iters % CHECK_INTERVAL == 0) or ((epoch == num_epochs-1) and (i == len(dataloader)-1)):
            with torch.no_grad():
                fake = generator(fixed_noise).detach().cpu()
            obs_size = fake.size(0)
            obs_size=obs_size//num_generators

            for g in range(num_generators):
                io.imsave(SAVE_DIR+'/Results/'+str(iters)+'_G'+str(g)+'.png', np.transpose(vutils.make_grid(fake[g*obs_size: (g+1)*obs_size], padding=2, normalize=True).cpu())


        iters = iters+1

        DEBUG=False