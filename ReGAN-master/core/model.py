import torch
import torch.nn as nn
import torchvision
import torch.nn.functional as F


def weights_init_normal(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        torch.nn.init.normal_(m.weight.data, 0.0, 0.02)
    elif classname.find('BatchNorm2d') != -1:
        torch.nn.init.normal_(m.weight.data, 1.0, 0.02)
        torch.nn.init.constant_(m.bias.data, 0.0)


class ResidualBlock(nn.Module):
    '''Residual Block with Instance Normalization'''

    def __init__(self, in_channels, out_channels):
        super(ResidualBlock, self).__init__()

        self.model = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False),
            nn.InstanceNorm2d(out_channels, affine=True, track_running_stats=True),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_channels, out_channels, kernel_size=3, stride=1, padding=1, bias=False),
            nn.InstanceNorm2d(out_channels, affine=True, track_running_stats=True),
        )

    def forward(self, x):
        return self.model(x) + x




class Double_conv(nn.Module):
    def __init__(self, in_channel, out_channel, keep_size=False):
        super(Double_conv, self).__init__()
        pad = 1 if keep_size else 0
        Layer = [
                 nn.Conv2d(in_channel, out_channel, 3, padding=pad),
                 nn.InstanceNorm2d(out_channel, affine=True, track_running_stats=True),
                 nn.ReLU(True),
                 nn.Conv2d(out_channel, out_channel, 3, padding=pad),
                 nn.InstanceNorm2d(out_channel, affine=True, track_running_stats=True),
                 nn.ReLU(True)
                ]
        self.dbl = nn.Sequential(*Layer)

    def forward(self, x):
        return self.dbl(x)


class Gen_Encoder(nn.Module):

    def __init__(self, in_channel, out_channel, keep_size=True):
        super(Gen_Encoder, self).__init__()
        self.conv = Double_conv(in_channel, out_channel, keep_size)
        self.pool = nn.MaxPool2d(2, 2)

    def forward(self, x):
        x = self.pool(x)
        x = self.conv(x)
        return x


class Gen_Decoder(nn.Module):
  def __init__(self, in_channels, middle_channels, out_channels):
    super(Gen_Decoder, self).__init__()
    self.up = nn.ConvTranspose2d(middle_channels, middle_channels, kernel_size=2, stride=2)
    self.AdaIN = nn.InstanceNorm2d(middle_channels, affine=True, track_running_stats=True)
    self.conv_relu = nn.Sequential(
        nn.Conv2d(middle_channels, out_channels, kernel_size=3, padding=1),
        nn.ReLU(inplace=True)
        )
  def forward(self, x1, x2):
    x1 = torch.cat((x1, x2), dim=1)
    x1 = self.up(x1)
    x1 = self.conv_relu(x1)

    return x1


class Generator(nn.Module):
    '''Generator with Down sampling, Several ResBlocks and Up sampling.
       Down/Up Samplings are used for less computation.
    '''

    def __init__(self, conv_dim, layer_num):
        super(Generator, self).__init__()

        input = []
        res_block = []
        output =[]

        # input layer
        input.append(nn.Conv2d(in_channels=3, out_channels=conv_dim, kernel_size=7, stride=1, padding=3, bias=False))
        input.append(nn.InstanceNorm2d(conv_dim, affine=True, track_running_stats=True))
        input.append(nn.ReLU(inplace=True))

        # down sampling layers
        current_dims = conv_dim
        self.down_layer1 = Gen_Encoder(current_dims, current_dims*2)
        self.down_layer2 = Gen_Encoder(current_dims*2, current_dims*4)
        self.down_layer3 = Gen_Encoder(current_dims*4, current_dims*8)

        # Residual Layers
        for i in range(layer_num):
            res_block.append(ResidualBlock(current_dims*8, current_dims*8))

        # up sampling layers
        self.up_layer3 = Gen_Decoder(current_dims*8, current_dims*8 + current_dims*8, current_dims*4)
        self.up_layer2 = Gen_Decoder(current_dims*4, current_dims*4 + current_dims*4, current_dims*2)
        self.up_layer1 = Gen_Decoder(current_dims*2, current_dims*2 + current_dims*2, current_dims)

        # output layer
        output.append(nn.Conv2d(current_dims, 3, kernel_size=7, stride=1, padding=3, bias=False))
        output.append(nn.Tanh())

        self.input = nn.Sequential(*input)
        self.res_block = nn.Sequential(*res_block)
        self.output = nn.Sequential(*output)

    def forward(self, x,):
        e0 = self.input(x)
        e1 = self.down_layer1(e0)
        e2 = self.down_layer2(e1)
        e3 = self.down_layer3(e2)
        f = self.res_block(e3)
        u3 = self.up_layer3(f, e3)
        u2 = self.up_layer2(u3, e2)
        u1 =self.up_layer1(u2, e1)
        out = self.output(u1)
        return out


class Discriminator(nn.Module):
    '''Discriminator with PatchGAN'''

    def __init__(self, image_size, conv_dim, layer_num):
        super(Discriminator, self).__init__()

        layers = []

        # input layer
        layers.append(nn.Conv2d(3, conv_dim, kernel_size=4, stride=2, padding=1))
        layers.append(nn.LeakyReLU(0.2, inplace=True))
        current_dim = conv_dim

        # hidden layers
        for i in range(layer_num):
            layers.append(nn.Conv2d(current_dim, current_dim*2, kernel_size=4, stride=2, padding=1))
            layers.append(nn.InstanceNorm2d(current_dim*2))
            layers.append(nn.LeakyReLU(0.2, inplace=True))
            current_dim *= 2

        self.model = nn.Sequential(*layers)

        # output layer
        self.conv_src = nn.Conv2d(current_dim, 1, kernel_size=3, stride=1, padding=1, bias=False)

    def forward(self, x):
        x = self.model(x)
        out_src = self.conv_src(x)
        return out_src



class ConditionalDiscriminator(nn.Module):
    '''Discriminator with PatchGAN'''

    def __init__(self, conv_dim):
        super(ConditionalDiscriminator, self).__init__()

        # image convs
        image_convs = []
        image_convs.append(nn.Conv2d(3, conv_dim, kernel_size=4, stride=2, padding=1))
        image_convs.append(nn.LeakyReLU(0.2, inplace=True))
        current_dim = conv_dim
        for i in range(2):
            image_convs.append(nn.Conv2d(current_dim, current_dim*2, kernel_size=4, stride=2, padding=1))
            image_convs.append(nn.InstanceNorm2d(current_dim*2))
            image_convs.append(nn.LeakyReLU(0.2, inplace=True))
            current_dim *= 2
        self.image_convs = nn.Sequential(*image_convs)

        # feature convs
        feature_convs = []
        feature_convs.append(nn.Conv2d(2048, conv_dim, kernel_size=1, stride=1, padding=0))
        feature_convs.append(nn.LeakyReLU(0.2, inplace=True))
        self.feature_convs = nn.Sequential(*feature_convs)

        # discriminator convs
        dis_convs = []
        dis_convs.append(nn.Conv2d(current_dim+conv_dim, current_dim*2, kernel_size=4, stride=2, padding=1))
        dis_convs.append(nn.InstanceNorm2d(current_dim*2))
        dis_convs.append(nn.LeakyReLU(0.2, inplace=True))
        current_dim *= 2
        dis_convs.append(nn.Conv2d(current_dim, current_dim * 2, kernel_size=4, stride=2, padding=1))
        dis_convs.append(nn.InstanceNorm2d(current_dim * 2))
        dis_convs.append(nn.LeakyReLU(0.2, inplace=True))
        current_dim *= 2
        self.dis_convs = nn.Sequential(*dis_convs)

        # output layer
        self.conv_src = nn.Conv2d(current_dim, 1, kernel_size=3, stride=1, padding=1, bias=False)

    def forward(self, images, features):
        images = self.image_convs(images)
        features = self.feature_convs(features)
        features = F.interpolate(features, [16, 16], mode='bilinear')
        x = torch.cat([images, features], dim=1)
        x = self.dis_convs(x)
        out_src = self.conv_src(x)
        return out_src


def weights_init_kaiming(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        nn.init.kaiming_normal_(m.weight.data, a=0, mode='fan_in')
    elif classname.find('Linear') != -1:
        nn.init.kaiming_normal_(m.weight.data, a=0, mode='fan_out')
        nn.init.constant_(m.bias.data, 0.0)
    elif classname.find('BatchNorm1d') != -1:
        nn.init.normal_(m.weight.data, 1.0, 0.02)
        nn.init.constant_(m.bias.data, 0.0)


def weights_init_classifier(m):
    classname = m.__class__.__name__
    if classname.find('Linear') != -1:
        nn.init.normal_(m.weight.data, std=0.001)
        nn.init.constant_(m.bias.data, 0.0)


class BottleClassifier(nn.Module):

    def __init__(self, in_dim, out_dim, relu=True, dropout=True, bottle_dim=512):
        super(BottleClassifier, self).__init__()

        bottle = [nn.Linear(in_dim, bottle_dim)]
        bottle += [nn.BatchNorm1d(bottle_dim)]
        if relu:
            bottle += [nn.LeakyReLU(0.1)]
        if dropout:
            bottle += [nn.Dropout(p=0.5)]
        bottle = nn.Sequential(*bottle)
        bottle.apply(weights_init_kaiming)
        self.bottle = bottle

        classifier = [nn.Linear(bottle_dim, out_dim)]
        classifier = nn.Sequential(*classifier)
        classifier.apply(weights_init_classifier)
        self.classifier = classifier

    def forward(self, x):
        x = self.bottle(x)
        x = self.classifier(x)
        return x



class Encoder(nn.Module):

    def __init__(self):
        super(Encoder, self).__init__()

        # load backbone and optimize its architecture
        resnet = torchvision.models.resnet50(pretrained=True)
        resnet.layer4[0].downsample[0].stride = (1,1)
        resnet.layer4[0].conv2.stride = (1,1)

        # cnn feature
        self.resnet_conv = nn.Sequential(resnet.conv1, resnet.bn1, resnet.relu, resnet.maxpool,
                                         resnet.layer1, resnet.layer2, resnet.layer3, resnet.layer4)

    def forward(self, x):

        return self.resnet_conv(x)


class Embeder(nn.Module):

    def __init__(self, part_num, class_num):
        super(Embeder, self).__init__()

        # parameters
        self.part_num = part_num
        self.class_num = class_num

        # pools
        avgpool = nn.AdaptiveAvgPool2d((self.part_num, 1))
        dropout = nn.Dropout(p=0.5)

        self.pool_c = nn.Sequential(avgpool, dropout)
        self.pool_e = nn.Sequential(avgpool)

        # classifier and embedders
        for i in range(part_num):
            name = 'classifier' + str(i)
            setattr(self, name, BottleClassifier(2048, self.class_num, relu=True, dropout=False, bottle_dim=256))
            name = 'embedder' + str(i)
            setattr(self, name, nn.Linear(2048, 256))

    def forward(self, features):

        features_c = torch.squeeze(self.pool_c(features))
        features_e = torch.squeeze(self.pool_e(features))

        logits_list = []
        for i in range(self.part_num):
            if self.part_num == 1:
                features_i = features_c
            else:
                features_i = torch.squeeze(features_c[:, :, i])
            classifier_i = getattr(self, 'classifier'+str(i))
            logits_i = classifier_i(features_i)
            logits_list.append(logits_i)

        embedding_list = []
        for i in range(self.part_num):
            if self.part_num == 1:
                features_i = features_e
            else:
                features_i = torch.squeeze(features_e[:, :, i])
            embedder_i = getattr(self, 'embedder'+str(i))
            embedding_i = embedder_i(features_i)
            embedding_list.append(embedding_i)

        return features_c, features_e, logits_list, embedding_list

