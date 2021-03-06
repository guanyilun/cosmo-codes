"""This script will contain useful functions and class for the
mcmc study."""

import numpy as np
import emcee
import dill as pickle

from cosmoslib.aps import Dl2Cl, resample
from cosmoslib.like import exact_likelihood


class MCMC(object):
    """Class for running MCMC"""
    def __init__(self, n_walkers=2, initial_delta=0.01, backend_file=None):
        self.n_walkers = n_walkers
        self.initial_delta = initial_delta
        self.sampler = None
        self.cosmology = None
        self.base_params = {}
        self.fit_params = {}
        self.fit_keys = []
        self.backend_file = backend_file
        self.likelihoods = []

    def set_params(self, params):
        """This method assigns parameters to the MCMC algorithm"""
        for k in params:
            if type(params[k]) is list:
                self.fit_params[k] = params[k]
            elif type(params[k]) is tuple:
                self.fit_params[k] = list(params[k])
            else:
                # otherwise it's a number -> base param
                self.base_params[k] = params[k]

        # update fit_keys
        self.fit_keys = [*self.fit_params]

        # update cosmology if it exists
        if self.cosmology:
            self.cosmology.set_model_params(self.base_params)

    def lnprior(self, theta):
        """This method looks at the fit params and transform it
        into priors"""
        for i, k in enumerate(self.fit_keys):
            lower = self.fit_params[k][0]
            fid = self.fit_params[k][1]
            upper = self.fit_params[k][2]

            p = theta[i]
            if p < lower:
                return -np.inf
            elif p > upper:
                return -np.inf
        return 0.

    def add_likelihood(self, likelihood):
        """Add a likelihood calculator"""
        self.likelihoods.append(likelihood)

    def set_cosmology(self, cm):
        """Supply a cosmology object that contains the base parameters"""
        self.cosmology = cm

        # update the base parameters
        self.cosmology.set_model_params(self.base_params)

    def generate_theory(self, theta):
        """This function takes the parameters and generate a theory power spectra"""
        # initialize an empty dict to store the model parameters
        model_params = {}
        for i, k in enumerate(self.fit_keys):
            model_params[k] = theta[i]

        self.cosmology.set_model_params(model_params)
        try:
            results = self.cosmology.full_run()
        except Exception as e:
            print("%s occurred, loglike=-np.inf" % type(e))
            import traceback; traceback.print_exc()
            return None, True  # the second return refers to error

        return results, False

    def lnprob(self, theta):
        ps_theory, err = self.generate_theory(theta)
        # if there is an error, reject this data point
        if err:
            return -np.inf

        # now i trust that there is no error
        prior = self.lnprior(theta)
        if np.isfinite(prior):
            for like_func in self.likelihoods:
                like += like_func(ps_theory)
            print("Parameter: %s\t loglike: %.2f" % (theta, like))
            return prior + like
        else:
            return -np.inf

    def run(self, N, pos0=None, resume=False, **kwargs):
        """Run the mcmc sampler with an ensemble sampler from emcee

        Parameters:
        ------------
        N: number of samples to be made for each
        pos0: initial positions, default to use built-in initial pos0
              generator, but it can be supplied manually
        resume: whether to resume from the checkpoint file
        **kwargs: remaining args will be passed to emcee.sample
        """
        self._counter = 0
        ndim = len(self.fit_keys)

        if self.n_walkers < 2*ndim:
            self.n_walkers = 2*ndim
            print("Warning: n_walkers too small, use %d instead..." \
                  % self.n_walkers)

        # load backends
        backend = emcee.backends.HDFBackend(self.backend_file)

        if resume:
            print("Initial number of steps: {0}".format(backend.iteration))
            # retrieve final position of chains
            samples = backend.get_chain()
            pos0 = samples.T[:,:,-1].T
        else:
            backend.reset(self.n_walkers, ndim)
            pos0 = self.generate_initial_pos()

        # check if n_walker satisfy the requirement that it
        # has to be even and more than 2*ndim
        sampler = emcee.EnsembleSampler(self.n_walkers, ndim,
                                        self.lnprob, backend=backend)
        if N > 0:
            self.sampler = sampler
            sampler.run_mcmc(pos0, N, **kwargs)

        return self.sampler

    def generate_initial_pos(self):
        """Generate the initial position for the mcmc"""
        pos0 = []
        ndim = len(self.fit_keys)
        for i in range(self.n_walkers):
            pos = np.array([self.fit_params[key][1] for key in
                            self.fit_keys])

            pos += np.random.randn(ndim)*self.initial_delta*pos
            pos0.append(pos)

        return pos0

    def reset_params(self):
        self.base_params = {}
        self.fit_params = {}
        self.fit_keys = []  # specify an ordering of the param keys

    def get_bf_params(self):
        # get best fit parameters
        whmax = self.sampler.flatlnprobability.argmax()
        bf_values = self.sampler.flatchain[whmax,:]

        bf_params = {}
        for i, k in enumerate(self.fit_keys):
            bf_params[k] = bf_values[i]

        return bf_params

    def get_bf_cosmology(self):
        import copy

        bf_params = self.get_bf_params()
        cosmology = copy.deepcopy(self.cosmology)

        cosmology.set_model_params(bf_params)
        return cosmology
