"""AnimeSR v2 inference network, derived from TencentARC/AnimeSR (Apache-2.0)."""

import torch
from torch import nn
from torch.nn import functional


class ResidualBlockNoBN(nn.Module):
    def __init__(self, num_feat: int = 64, res_scale: float = 1.0):
        super().__init__()
        self.res_scale = res_scale
        self.conv1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.conv2(self.relu(self.conv1(x))) * self.res_scale


class RightAlignMSConvResidualBlocks(nn.Module):
    def __init__(
        self,
        num_in_ch: int = 3,
        num_state_ch: int = 64,
        num_out_ch: int = 64,
        num_block: tuple[int, int, int] = (5, 3, 2),
    ):
        super().__init__()
        if not len(num_block) == 3 or not num_block[0] >= num_block[1] >= num_block[2]:
            raise ValueError("AnimeSR requires three descending block counts")
        self.num_block = num_block
        self.conv_s1_first = nn.Sequential(
            nn.Conv2d(num_in_ch, num_state_ch, 3, 1, 1),
            nn.LeakyReLU(negative_slope=0.1, inplace=True),
        )
        self.conv_s2_first = nn.Sequential(
            nn.Conv2d(num_state_ch, num_state_ch, 3, 2, 1),
            nn.LeakyReLU(negative_slope=0.1, inplace=True),
        )
        self.conv_s4_first = nn.Sequential(
            nn.Conv2d(num_state_ch, num_state_ch, 3, 2, 1),
            nn.LeakyReLU(negative_slope=0.1, inplace=True),
        )
        self.body_s1_first = nn.ModuleList(
            ResidualBlockNoBN(num_state_ch) for _ in range(num_block[0])
        )
        self.body_s2_first = nn.ModuleList(
            ResidualBlockNoBN(num_state_ch) for _ in range(num_block[1])
        )
        self.body_s4_first = nn.ModuleList(
            ResidualBlockNoBN(num_state_ch) for _ in range(num_block[2])
        )
        self.upsample_x2 = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)
        self.upsample_x4 = nn.Upsample(scale_factor=4, mode="bilinear", align_corners=False)
        self.fusion = nn.Sequential(
            nn.Conv2d(3 * num_state_ch, 2 * num_out_ch, 3, 1, 1),
            nn.LeakyReLU(negative_slope=0.1, inplace=True),
            nn.Conv2d(2 * num_out_ch, num_out_ch, 3, 1, 1),
        )

    def up(self, x: torch.Tensor | int, scale: int = 2) -> torch.Tensor | int:
        if isinstance(x, int):
            return x
        return self.upsample_x2(x) if scale == 2 else self.upsample_x4(x)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x_s1 = self.conv_s1_first(x)
        x_s2 = self.conv_s2_first(x_s1)
        x_s4 = self.conv_s4_first(x_s2)
        flag_s2 = False
        flag_s4 = False
        for index in range(self.num_block[0]):
            x_s1 = self.body_s1_first[index](
                x_s1
                + (self.up(x_s2, 2) if flag_s2 else 0)
                + (self.up(x_s4, 4) if flag_s4 else 0)
            )
            if index >= self.num_block[0] - self.num_block[1]:
                body_index = index - self.num_block[0] + self.num_block[1]
                x_s2 = self.body_s2_first[body_index](
                    x_s2 + (self.up(x_s4, 2) if flag_s4 else 0)
                )
                flag_s2 = True
            if index >= self.num_block[0] - self.num_block[2]:
                body_index = index - self.num_block[0] + self.num_block[2]
                x_s4 = self.body_s4_first[body_index](x_s4)
                flag_s4 = True
        return self.fusion(
            torch.cat((x_s1, self.upsample_x2(x_s2), self.upsample_x4(x_s4)), dim=1)
        )


class AnimeSRV2(nn.Module):
    def __init__(
        self,
        num_feat: int = 64,
        num_block: tuple[int, int, int] = (5, 3, 2),
        netscale: int = 4,
    ):
        super().__init__()
        input_channels = 3 * 3 + 3 * netscale * netscale + num_feat
        output_channels = num_feat + 3 * netscale * netscale
        self.recurrent_cell = RightAlignMSConvResidualBlocks(
            input_channels, num_feat, output_channels, num_block
        )
        self.lrelu = nn.LeakyReLU(negative_slope=0.1)
        self.pixel_shuffle = nn.PixelShuffle(netscale)
        self.netscale = netscale

    def cell(
        self, x: torch.Tensor, feedback: torch.Tensor, state: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor]:
        residual = x[:, 3:6]
        model_input = torch.cat(
            (x, functional.pixel_unshuffle(feedback, self.netscale), state), dim=1
        )
        output = self.recurrent_cell(model_input)
        image_channels = 3 * self.netscale * self.netscale
        output_image = self.pixel_shuffle(output[:, :image_channels]) + functional.interpolate(
            residual, scale_factor=self.netscale, mode="bilinear", align_corners=False
        )
        output_state = self.lrelu(output[:, image_channels:])
        return output_image, output_state
