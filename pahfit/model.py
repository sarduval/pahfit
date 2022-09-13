from specutils import Spectrum1D
from features import Features
from base import PAHFITBase
from astropy import units as u
import copy
from astropy.modeling.fitting import LevMarLSQFitter
from matplotlib import pyplot as plt


class Model:
    """This class acts as the main API for PAHFIT.

    The users deal with model objects, of which the state is modified
    during initalization, initial guessing, and fitting. What the model
    STORES is a description of the physics: what features are there and
    what are their properties, regardless of the instrument with which
    those features are observed. The methods provided by this class,
    form the connection between those physics, and what is observed.
    During fitting and plotting, those physics are converted into a
    model for the observation, by applying instrumental parameters from
    the instrument.py module.

    The main thing that defines a model, is the features table, loaded
    from a YAML file given to the constructor. After construction, the
    Model can be edited by accessing the stored features table directly.
    Changing numbers in this table, is allowed, and the updated numbers
    will be reflected when the next fit or initial guess happens. At the
    end of these actions, the fit or guess results are stored in the
    same table.

    The model can be saved.

    The model can be copied.

    Attributes
    ----------
    features : Features
        Instance of the Features class. Can be edited on-the-fly.
        Non-breaking behavior by the user is expected. Changes will be
        reflected at the next fit, guess, or plot call.

    """

    def __init__(self, features: Features, instrumentname, redshift):
        """
        Parameters
        ----------
        features: Features
            Features table.

        instrumentname : str or list of str
            Qualified instrument name, see instrument.py. This will
            determine what the line widths are, when going from the features
            table to a fittable/plottable model.

        redshift : float
            Redshift used to shift from the physical model, to the observed model.
        """
        self.redshift = redshift
        self.instrumentname = instrumentname
        self.features = features

    @classmethod
    def from_yaml(cls, pack_file, instrumentname, redshift):
        """
        Parameters
        ----------
        pack_file : str
            Path to YAML file, or path to stored results table. The feature
            table is generated based on this input.

        Returns
        -------
        Model instance

        """
        features = Features.read(pack_file)
        return cls(features, instrumentname, redshift)

    @classmethod
    def from_saved(cls, saved_model_file):
        """
        Parameters
        ----------
        saved_model_file : str
           File generated by Model.save()

        Returns
        -------
        Model instance
        """
        # features.read automatically switches to astropy table reader.
        # Maybe needs to be more advanced here in the future. TODO: make
        # sure we get the metadata too! Redshift, uncertinties (fit
        # result parameters are already stored in the main table, so
        # that should be fine)
        features = Features.read(saved_model_file)
        metadata_mock = {"redshift": 0.0, "instrumentname": "bla"}
        return cls(features, metadata_mock["instrumentname"], metadata_mock["redshift"])

    def guess(self, spec: Spectrum1D):
        """Make an initial guess of the physics, based on the given
        observational data.

        Parameters
        ----------
        spec : Spectrum1D
            1D (not 2D or 3D) spectrum object, containing the
            observational data. (TODO: should support list of spectra,
            for the segment-based joint fitting). Initial guess will be
            based on the flux in this spectrum.

        Returns
        -------
        Nothing, but internal feature table is updated.

        """
        obs_x = spec.spectral_axis.to(u.micron).value
        obs_y = spec.flux.value  # TODO figure out right unit

        # remake param_info to make sure we have any feature updates from the user
        param_info = self._kludge_param_info()
        param_info = PAHFITBase.estimate_init(obs_x, obs_y, param_info)
        self._backport_param_info(param_info)

    def fit(self, spec: Spectrum1D, maxiter=1000, verbose=True):
        """Create a model, fit it, and store the results in the features table

        Parameters
        ----------
        spec : Spectrum1D

        maxiter : int
            maximum number of fitting iterations

        verbose : boolean
            set to provide screen output

        """
        astropy_model = self._construct_astropy_model()

        # pick the fitter
        fit = LevMarLSQFitter()

        # fit
        x = spec.spectral_axis.to(u.micon).value
        y = spec.flux.value
        w = 1.0 / spec.uncertainty.value
        self.astropy_result = fit(
            astropy_model,
            x,
            y,
            weights=w,
            maxiter=maxiter,
            epsilon=1e-10,
            acc=1e-10,
        )
        if verbose:
            print(fit.fit_info["message"])

        self._parse_astropy_result(self.astropy_result)

    def info(self):
        """Print out the last fit results."""
        print(self.astropy_result)

    def plot(self, spec=None):
        """Plot model, and optionally compare to observational data.

        Parameters
        ----------
        spec : Spectrum1D
            Observational data. Does not have to be the same data that
            was used for guessing or fitting.
        """
        # copied some stuff from plot_pahfit
        fig, axs = plt.subplots(
            ncols=1,
            nrows=2,
            figsize=(15, 10),
            gridspec_kw={"height_ratios": [3, 1]},
            sharex=True,
        )

        x = spec.spectral_axis.to(u.micon).value
        y = spec.flux.value
        u = spec.uncertainty.value
        astropy_model = self._construct_astropy_model()
        PAHFITBase.plot(axs, x, y, u, astropy_model)

        fig.subplots_adjust(hspace=0)

    def copy(self):
        """Copy the model.

        Main use case: use this model as a parent model for more
        fits.

        Currently uses copy.deepcopy. We should do something smarter if
        we run into memory problems or sluggishness.

        Returns
        -------
        model_copy : Model
        """
        # We could do this
        # make new instance
        # model_copy = type(self)(self.pack_file, self.instrumentname, self.redshift)
        # copy over all the variables that might have changed
        # make sure to deep copy the table!

        # But maybe try this first
        return copy.deepcopy(self)

    def save(self, fn):
        """Save the model to disk.

        This will save the features table using its builtin write
        function from astropy.table.

        Format TDB. Currently depends on file extension given, same as
        astropy.

        Models saved this way can be read in.

        Parameters
        ----------
        fn : file name

        """
        self.features.write(fn)

    def _kludge_param_info(self):
        param_info = PAHFITBase.parse_table(self.features)
        # edit line widths and drop lines out of range
        param_info[2] = PAHFITBase.update_dictionary(
            param_info[2], self.instrumentname, update_fwhms=True
        )
        param_info[3] = PAHFITBase.update_dictionary(
            param_info[3], self.instrumentname, update_fwhms=True
        )
        return param_info

    def _backport_param_info(self, param_info):
        """Convert param_info to values in features table.

        Temporary hack to make the new system compatible with the old system.

        """
        raise NotImplementedError
        # unfortunately, there is no implementation for this, even in
        # the original code. That one goes straight from astropy model
        # to table...
        # But we can do something wacky here, like converting to model
        # first, and then back to table.
        astropy_model = PAHFITBase.model_from_param_info(param_info)
        self._parse_astropy_result(astropy_model)

    def _construct_astropy_model(self):
        """Convert the features table into a fittable model."""
        param_info = self._kludge_param_info()
        return PAHFITBase.model_from_param_info(param_info)

    def _parse_astropy_result(self, astropy_model):
        """Store the result of the astropy fit into the features table

        Every relevant value inside the astropy model, is written to the
        right position in the features table. This way, the astropy
        model and the features table are kept in sync.

        Doing things this way, makes it possible for the user to make
        edits to the features table, and makes it easy to store the
        model (just store the features table)

        """
        # implementation inspired by pahfitbase. I think I better
        # rewrite this thing from the start. Plenty of ways to test if
        # it's correct.
        raise NotImplementedError
        pass
