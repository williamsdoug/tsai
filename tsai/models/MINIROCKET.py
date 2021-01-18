# AUTOGENERATED! DO NOT EDIT! File to edit: nbs/111b_models.MINIROCKET.ipynb (unless otherwise specified).

__all__ = ['fit', 'transform', 'MINIROCKET', 'MINIROCKETv2', 'get_minirocket_features', 'MiniRocket']

# Cell
from ..imports import *
from ..data.external import *
from .layers import *

# Cell

# minirocket_multivariate.py from https://github.com/angus924/minirocket

# Angus Dempster, Daniel F Schmidt, Geoffrey I Webb

# MiniRocket: A Very Fast (Almost) Deterministic Transform for Time Series
# Classification

# https://arxiv.org/abs/2012.08791
# Original code: https://github.com/angus924/minirocket

from numba import njit, prange, vectorize
import numpy as np


@njit("float32[:](float32[:,:,:],int32[:],int32[:],int32[:],int32[:],float32[:])", fastmath = True, parallel = False, cache = True)
def _fit_biases(X, num_channels_per_combination, channel_indices, dilations, num_features_per_dilation, quantiles):

    num_examples, num_channels, input_length = X.shape

    # equivalent to:
    # >>> from itertools import combinations
    # >>> indices = np.array([_ for _ in combinations(np.arange(9), 3)], dtype = np.int32)
    indices = np.array((
        0,1,2,0,1,3,0,1,4,0,1,5,0,1,6,0,1,7,0,1,8,
        0,2,3,0,2,4,0,2,5,0,2,6,0,2,7,0,2,8,0,3,4,
        0,3,5,0,3,6,0,3,7,0,3,8,0,4,5,0,4,6,0,4,7,
        0,4,8,0,5,6,0,5,7,0,5,8,0,6,7,0,6,8,0,7,8,
        1,2,3,1,2,4,1,2,5,1,2,6,1,2,7,1,2,8,1,3,4,
        1,3,5,1,3,6,1,3,7,1,3,8,1,4,5,1,4,6,1,4,7,
        1,4,8,1,5,6,1,5,7,1,5,8,1,6,7,1,6,8,1,7,8,
        2,3,4,2,3,5,2,3,6,2,3,7,2,3,8,2,4,5,2,4,6,
        2,4,7,2,4,8,2,5,6,2,5,7,2,5,8,2,6,7,2,6,8,
        2,7,8,3,4,5,3,4,6,3,4,7,3,4,8,3,5,6,3,5,7,
        3,5,8,3,6,7,3,6,8,3,7,8,4,5,6,4,5,7,4,5,8,
        4,6,7,4,6,8,4,7,8,5,6,7,5,6,8,5,7,8,6,7,8
    ), dtype = np.int32).reshape(84, 3)

    num_kernels = len(indices)
    num_dilations = len(dilations)

    num_features = num_kernels * np.sum(num_features_per_dilation)

    biases = np.zeros(num_features, dtype = np.float32)

    feature_index_start = 0

    combination_index = 0
    num_channels_start = 0

    for dilation_index in range(num_dilations):

        dilation = dilations[dilation_index]
        padding = ((9 - 1) * dilation) // 2

        num_features_this_dilation = num_features_per_dilation[dilation_index]

        for kernel_index in range(num_kernels):

            feature_index_end = feature_index_start + num_features_this_dilation

            num_channels_this_combination = num_channels_per_combination[combination_index]

            num_channels_end = num_channels_start + num_channels_this_combination

            channels_this_combination = channel_indices[num_channels_start:num_channels_end]

            _X = X[np.random.randint(num_examples)][channels_this_combination]

            A = -_X          # A = alpha * X = -X
            G = _X + _X + _X # G = gamma * X = 3X

            C_alpha = np.zeros((num_channels_this_combination, input_length), dtype = np.float32)
            C_alpha[:] = A

            C_gamma = np.zeros((9, num_channels_this_combination, input_length), dtype = np.float32)
            C_gamma[9 // 2] = G

            start = dilation
            end = input_length - padding

            for gamma_index in range(9 // 2):

                C_alpha[:, -end:] = C_alpha[:, -end:] + A[:, :end]
                C_gamma[gamma_index, :, -end:] = G[:, :end]

                end += dilation

            for gamma_index in range(9 // 2 + 1, 9):

                C_alpha[:, :-start] = C_alpha[:, :-start] + A[:, start:]
                C_gamma[gamma_index, :, :-start] = G[:, start:]

                start += dilation

            index_0, index_1, index_2 = indices[kernel_index]

            C = C_alpha + C_gamma[index_0] + C_gamma[index_1] + C_gamma[index_2]
            C = np.sum(C, axis = 0)

            biases[feature_index_start:feature_index_end] = np.quantile(C, quantiles[feature_index_start:feature_index_end])

            feature_index_start = feature_index_end

            combination_index += 1
            num_channels_start = num_channels_end

    return biases

def _fit_dilations(input_length, num_features, max_dilations_per_kernel):

    num_kernels = 84

    num_features_per_kernel = num_features // num_kernels
    true_max_dilations_per_kernel = min(num_features_per_kernel, max_dilations_per_kernel)
    multiplier = num_features_per_kernel / true_max_dilations_per_kernel

    max_exponent = np.log2((input_length - 1) / (9 - 1))
    dilations, num_features_per_dilation = \
    np.unique(np.logspace(0, max_exponent, true_max_dilations_per_kernel, base = 2).astype(np.int32), return_counts = True)
    num_features_per_dilation = (num_features_per_dilation * multiplier).astype(np.int32) # this is a vector

    remainder = num_features_per_kernel - np.sum(num_features_per_dilation)
    i = 0
    while remainder > 0:
        num_features_per_dilation[i] += 1
        remainder -= 1
        i = (i + 1) % len(num_features_per_dilation)

    return dilations, num_features_per_dilation

# low-discrepancy sequence to assign quantiles to kernel/dilation combinations
def _quantiles(n):
    return np.array([(_ * ((np.sqrt(5) + 1) / 2)) % 1 for _ in range(1, n + 1)], dtype = np.float32)

def fit(X, num_features = 10_000, max_dilations_per_kernel = 32):

    _, num_channels, input_length = X.shape

    num_kernels = 84

    dilations, num_features_per_dilation = _fit_dilations(input_length, num_features, max_dilations_per_kernel)

    num_features_per_kernel = np.sum(num_features_per_dilation)

    quantiles = _quantiles(num_kernels * num_features_per_kernel)

    num_dilations = len(dilations)
    num_combinations = num_kernels * num_dilations

    max_num_channels = min(num_channels, 9)
    max_exponent = np.log2(max_num_channels + 1)

    num_channels_per_combination = (2 ** np.random.uniform(0, max_exponent, num_combinations)).astype(np.int32)

    channel_indices = np.zeros(num_channels_per_combination.sum(), dtype = np.int32)

    num_channels_start = 0
    for combination_index in range(num_combinations):
        num_channels_this_combination = num_channels_per_combination[combination_index]
        num_channels_end = num_channels_start + num_channels_this_combination
        channel_indices[num_channels_start:num_channels_end] = np.random.choice(num_channels, num_channels_this_combination, replace = False)

        num_channels_start = num_channels_end

    biases = _fit_biases(X, num_channels_per_combination, channel_indices, dilations, num_features_per_dilation, quantiles)

    return num_channels_per_combination, channel_indices, dilations, num_features_per_dilation, biases

# _PPV(C, b).mean() returns PPV for vector C (convolution output) and scalar b (bias)
@vectorize("float32(float32,float32)", nopython = True, cache = True)
def _PPV(a, b):
    if a > b:
        return 1
    else:
        return 0

@njit("float32[:,:](float32[:,:,:],Tuple((int32[:],int32[:],int32[:],int32[:],float32[:])))", fastmath = True, parallel = True, cache = True)
def transform(X, parameters):

    num_examples, num_channels, input_length = X.shape

    num_channels_per_combination, channel_indices, dilations, num_features_per_dilation, biases = parameters

    # equivalent to:
    # >>> from itertools import combinations
    # >>> indices = np.array([_ for _ in combinations(np.arange(9), 3)], dtype = np.int32)
    indices = np.array((
        0,1,2,0,1,3,0,1,4,0,1,5,0,1,6,0,1,7,0,1,8,
        0,2,3,0,2,4,0,2,5,0,2,6,0,2,7,0,2,8,0,3,4,
        0,3,5,0,3,6,0,3,7,0,3,8,0,4,5,0,4,6,0,4,7,
        0,4,8,0,5,6,0,5,7,0,5,8,0,6,7,0,6,8,0,7,8,
        1,2,3,1,2,4,1,2,5,1,2,6,1,2,7,1,2,8,1,3,4,
        1,3,5,1,3,6,1,3,7,1,3,8,1,4,5,1,4,6,1,4,7,
        1,4,8,1,5,6,1,5,7,1,5,8,1,6,7,1,6,8,1,7,8,
        2,3,4,2,3,5,2,3,6,2,3,7,2,3,8,2,4,5,2,4,6,
        2,4,7,2,4,8,2,5,6,2,5,7,2,5,8,2,6,7,2,6,8,
        2,7,8,3,4,5,3,4,6,3,4,7,3,4,8,3,5,6,3,5,7,
        3,5,8,3,6,7,3,6,8,3,7,8,4,5,6,4,5,7,4,5,8,
        4,6,7,4,6,8,4,7,8,5,6,7,5,6,8,5,7,8,6,7,8
    ), dtype = np.int32).reshape(84, 3)

    num_kernels = len(indices)
    num_dilations = len(dilations)

    num_features = num_kernels * np.sum(num_features_per_dilation)

    features = np.zeros((num_examples, num_features), dtype = np.float32)

    for example_index in prange(num_examples):

        _X = X[example_index]

        A = -_X          # A = alpha * X = -X
        G = _X + _X + _X # G = gamma * X = 3X

        feature_index_start = 0

        combination_index = 0
        num_channels_start = 0

        for dilation_index in range(num_dilations):

            _padding0 = dilation_index % 2

            dilation = dilations[dilation_index]
            padding = ((9 - 1) * dilation) // 2

            num_features_this_dilation = num_features_per_dilation[dilation_index]

            C_alpha = np.zeros((num_channels, input_length), dtype = np.float32)
            C_alpha[:] = A

            C_gamma = np.zeros((9, num_channels, input_length), dtype = np.float32)
            C_gamma[9 // 2] = G

            start = dilation
            end = input_length - padding

            for gamma_index in range(9 // 2):

                C_alpha[:, -end:] = C_alpha[:, -end:] + A[:, :end]
                C_gamma[gamma_index, :, -end:] = G[:, :end]

                end += dilation

            for gamma_index in range(9 // 2 + 1, 9):

                C_alpha[:, :-start] = C_alpha[:, :-start] + A[:, start:]
                C_gamma[gamma_index, :, :-start] = G[:, start:]

                start += dilation

            for kernel_index in range(num_kernels):

                feature_index_end = feature_index_start + num_features_this_dilation

                num_channels_this_combination = num_channels_per_combination[combination_index]

                num_channels_end = num_channels_start + num_channels_this_combination

                channels_this_combination = channel_indices[num_channels_start:num_channels_end]

                _padding1 = (_padding0 + kernel_index) % 2

                index_0, index_1, index_2 = indices[kernel_index]

                C = C_alpha[channels_this_combination] + \
                    C_gamma[index_0][channels_this_combination] + \
                    C_gamma[index_1][channels_this_combination] + \
                    C_gamma[index_2][channels_this_combination]
                C = np.sum(C, axis = 0)

                if _padding1 == 0:
                    for feature_count in range(num_features_this_dilation):
                        features[example_index, feature_index_start + feature_count] = _PPV(C, biases[feature_index_start + feature_count]).mean()
                else:
                    for feature_count in range(num_features_this_dilation):
                        features[example_index, feature_index_start + feature_count] = _PPV(C[padding:-padding], biases[feature_index_start + feature_count]).mean()

                feature_index_start = feature_index_end

                combination_index += 1
                num_channels_start = num_channels_end

    return features

# Cell
# This is an unofficial MINIROCKET implementation in Pytorch developed by Ignacio Oguiza - timeseriesAI@gmail.com based on:
# Dempster, A., Schmidt, D. F., & Webb, G. I. (2020). MINIROCKET: A Very Fast (Almost) Deterministic Transform for Time Series Classification.
# arXiv preprint arXiv:2012.08791.
# Official repo: https://github.com/angus924/minirocket

class MINIROCKET(nn.Module):
    def __init__(self, c_in, c_out, seq_len=1, bn=False, fc_dropout=0., custom_head=None, **kwargs):
        """
        MINIROCKET implementation where features are previously calculated.
        Args:
            c_in: number of features per sample. For 10_000 kernels iw will be 9996.
            c_out: number of classes.
            seq_len: For MINIROCKET this is always 1 as features are previously calculated. For compatibility.
            bn: indicates whether batchnorm should be used in the models head
            fc_dropout: indicates whether dropout should be added to the last fully connected layer
            custom_head: used when a different type of head needs to be applied
        """
        super().__init__()
        self.head_nf = c_in
        if custom_head is not None:
            self.head = custom_head(c_in, c_out, seq_len, bn=bn, fc_dropout=fc_dropout, **kwargs)
        else:
            layers = []
            if bn: layers += [nn.BatchNorm1d(c_in)]
            if fc_dropout: layers += [nn.Dropout(fc_dropout)]
            linear = nn.Linear(c_in, c_out)
            nn.init.constant_(linear.weight.data, 0)
            nn.init.constant_(linear.bias.data, 0)
            layers += [linear]
            self.head = nn.Sequential(*layers)

    def forward(self, x):
        return self.head(x.squeeze(-1))

# Cell
# This is an unofficial MINIROCKET implementation in Pytorch developed by Ignacio Oguiza - timeseriesAI@gmail.com based on:
# Dempster, A., Schmidt, D. F., & Webb, G. I. (2020). MINIROCKET: A Very Fast (Almost) Deterministic Transform for Time Series Classification.
# arXiv preprint arXiv:2012.08791.
# Official repo: https://github.com/angus924/minirocket

class MINIROCKETv2(nn.Module):
    def __init__(self, c_in, c_out, seq_len, num_features=10_000, max_dilations_per_kernel=32, bn=False, fc_dropout=0., eps=1e-8, custom_head=None, **kwargs):
        """
        MINIROCKET implementation where features are calculated within the model (once per batch).
        Args:
            c_in: number of variables of the time series.
            c_out: number of classes.
            seq_len: length of the time series.
            num_features: number of rocket features that will be calculated. Defaults to 10_000.
            max_dilations_per_kernel: number of dilations used per kernel when calculating features. Defaults to 32.
            bn: indicates whether batchnorm should be used in the models head.
            fc_dropout: indicates whether dropout should be added to the last fully connected layer.
            eps: used to avoid division by zero.
            custom_head: used when a different type of head needs to be applied.
        """
        super().__init__()
        self.c_in, self.num_features, self.max_dilations_per_kernel, self.eps = c_in, num_features, max_dilations_per_kernel, eps
        self.rocket_params = None
        self.f_mean, self.f_std = None, None
        self.fit = fit
        self.tfm = transform
        self.head_nf = 84 * (num_features // 84)
        if custom_head is not None:
            self.head = custom_head(self.head_nf, c_out, 1, bn=bn, fc_dropout=fc_dropout, **kwargs)
        else:
            layers = []
            if bn: layers += [nn.BatchNorm1d(self.head_nf)]
            if fc_dropout: layers += [nn.Dropout(fc_dropout)]
            layers += [Squeeze(-1)]
            linear = nn.Linear(self.head_nf, c_out)
            nn.init.constant_(linear.weight.data, 0)
            nn.init.constant_(linear.bias.data, 0)
            layers += [linear]
            self.head = nn.Sequential(*layers)

    def forward(self, x):
        with torch.no_grad():
            if self.rocket_params is None:
                self.rocket_params = self.fit(x.cpu().numpy(), self.num_features, self.max_dilations_per_kernel)
            x_tfm = x.new(self.tfm(x.cpu().numpy(), self.rocket_params)).unsqueeze(-1)
            if self.f_mean is None:
                self.f_mean = x_tfm.mean(0)
                self.f_std = x_tfm.std(0) + self.eps
            x_tfm = (x_tfm - self.f_mean) / self.f_std
        return self.head(x_tfm)

# Cell
def get_minirocket_features(X, num_features=10_000, max_dilations_per_kernel=32, on_disk=True, path='./data/MINIROCKET', fname='X_tfm'):
    rocket_params = fit(X, num_features=num_features, max_dilations_per_kernel=max_dilations_per_kernel)
    X_tfm = transform(X, rocket_params)[..., None]
    del X
    gc.collect()
    if on_disk:
        full_fname = Path(path)/f'{fname}.npy'
        if not os.path.exists(Path(path)): os.makedirs(Path(path))
        np.save(full_fname, X_tfm)
        del X_tfm
        X_tfm = np.load(full_fname, mmap_mode='r+')
    return X_tfm

# Cell
from sklearn.pipeline import make_pipeline
from sktime.transformations.panel.rocket import MiniRocketMultivariate
class MiniRocket(sklearn.pipeline.Pipeline):
    def __init__(self, num_features=10000, max_dilations_per_kernel=32, random_state=None,
                 alphas=np.logspace(-3, 3, 10), *, normalize=True, memory=None, verbose=False, **kwargs):
        self.steps = [('minirocketmultivariate', MiniRocketMultivariate(num_features=num_features,
                                                                        max_dilations_per_kernel=max_dilations_per_kernel,
                                                                        random_state=random_state)),
                      ('ridgeclassifiercv', RidgeClassifierCV(alphas=alphas, normalize=normalize, **kwargs))]
        self.num_features, self.max_dilations_per_kernel, self.random_state = num_features, max_dilations_per_kernel, random_state
        self.alphas, self.normalize, self.kwargs = alphas, normalize, kwargs
        self.memory = memory
        self.verbose = verbose
        self._validate_steps()