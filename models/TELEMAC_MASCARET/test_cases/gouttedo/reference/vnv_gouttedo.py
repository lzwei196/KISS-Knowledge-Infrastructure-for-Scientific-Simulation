"""
Validation script for gouttedo
"""
from vvytel.vnv_study import AbstractVnvStudy
from execution.telemac_cas import TelemacCas, get_dico
from data_manip.extraction.telemac_file import TelemacFile

class VnvStudy(AbstractVnvStudy):
    """
    Class for validation
    """

    def _init(self):
        """
        Defining general parameters
        """
        self.rank = 4
        self.tags = ['telemac2d', 'fv']

    def _pre(self):
        """
        Defining the studies
        """

        # Default run
        self.add_study('seq',
                       'telemac2d',
                       't2d_gouttedo.cas')

        cas = TelemacCas('t2d_gouttedo.cas', get_dico('telemac2d'))
        cas.set('PARALLEL PROCESSORS', 4)

        self.add_study('par',
                       'telemac2d',
                       't2d_gouttedo_par.cas',
                       cas=cas)

        del cas

        # Quadratic run
        cas = TelemacCas('t2d_gouttedo.cas', get_dico('telemac2d'))
        cas.set('TYPE OF ADVECTION', [1, 5])
        cas.set('DISCRETIZATIONS IN SPACE', [13, 11])
        cas.set('RESULTS FILE', 'r2d_gouttedo_qua.slf')
        cas.remove('SUPG OPTION')

        self.add_study('qua_seq',
                       'telemac2d',
                       't2d_gouttedo_qua_seq.cas',
                       cas=cas)

        cas.set('PARALLEL PROCESSORS', 4)
        self.add_study('qua_par',
                       'telemac2d',
                       't2d_gouttedo_qua_par.cas',
                       cas=cas)

        del cas

        # Cinetic run
        cas = TelemacCas('t2d_gouttedo.cas', get_dico('telemac2d'))
        cas.set('EQUATIONS', 'SAINT-VENANT FV')
        cas.set('FINITE VOLUME SCHEME', 1)
        cas.set('VARIABLE TIME-STEP', True)
        cas.set('DURATION', 4.)
        cas.set('DESIRED COURANT NUMBER', 0.9)
        cas.set('LISTING FOR PRINTOUT PERIOD',100)
        cas.set('RESULTS FILE', 'r2d_gouttedo_cin.slf')
        cas.set('NUMBER OF TRACERS', 1)
        cas.set('NAMES OF TRACERS', 'TRACER 1        NO UNIT         ')
        cas.set('FINITE VOLUME SCHEME SPACE ORDER',2)
        cas.remove('SOLVER')
        cas.remove('SOLVER OPTION')
        cas.remove('MAXIMUM NUMBER OF ITERATIONS FOR SOLVER')
        cas.remove('SOLVER ACCURACY')
        cas.remove('IMPLICITATION FOR DEPTH')
        cas.remove('IMPLICITATION FOR VELOCITY')
        cas.remove('TYPE OF ADVECTION')
        cas.remove('SUPG OPTION')
        cas.remove('DISCRETIZATIONS IN SPACE')

        self.add_study('cin',
                       'telemac2d',
                       't2d_gouttedo_cin.cas',
                       cas=cas)
        del cas

        # Concat run
        cas = TelemacCas('t2d_gouttedo.cas', get_dico('telemac2d'))
        cas.set('CONCATENATE PARTEL OUTPUT', True)
        cas.set('PARALLEL PROCESSORS', 4)

        self.add_study('concat',
                       'telemac2d',
                       't2d_gouttedo_concat.cas',
                       cas=cas)
        del cas

        # Reprod run
        cas = TelemacCas('t2d_gouttedo.cas', get_dico('telemac2d'))
        cas.set('FINITE ELEMENT ASSEMBLY', 3)
        cas.set('SOLVER', 1)
        cas.set('PRECONDITIONING', 0)
        cas.set('TYPE OF ADVECTION', [1, 5])
        cas.set('MATRIX STORAGE', 1)
        cas.set('MATRIX-VECTOR PRODUCT', 1)
        cas.set('TREATMENT OF THE LINEAR SYSTEM', 2)
        cas.remove('SUPG OPTION')
        cas.remove('SOLVER OPTION')

        self.add_study('reprod_seq',
                       'telemac2d',
                       't2d_gouttedo_reprod_seq.cas',
                       cas=cas)

        cas.set('PARALLEL PROCESSORS', 4)
        self.add_study('reprod_par',
                       'telemac2d',
                       't2d_gouttedo_reprod_par.cas',
                       cas=cas)

        del cas


    def _check_results(self):
        """
        Check on run results
        """
        # Epsilons for default run
        self.check_epsilons('seq:T2DRES',
                            'f2d_gouttedo.slf',
                            eps=[1e-7])
        self.check_epsilons('par:T2DRES',
                            'f2d_gouttedo.slf',
                            eps=[1e-7])
        self.check_epsilons('seq:T2DRES',
                            'par:T2DRES',
                            eps=[1e-7])

        # Espilons for Quadratic run
        self.check_epsilons('qua_seq:T2DRES',
                            'f2d_gouttedo_qua.slf',
                            eps=[1e-1])
        self.check_epsilons('qua_par:T2DRES',
                            'f2d_gouttedo_qua.slf',
                            eps=[1e-1])
        self.check_epsilons('qua_seq:T2DRES',
                            'qua_par:T2DRES',
                            eps=[1e-7])

        # Epsilon for cinetic run
        self.check_epsilons('cin:T2DRES',
                            'f2d_gouttedo_cin.slf',
                            eps=[1e-1])

        # Epsilon for reproductibility case
        self.check_epsilons('reprod_seq:T2DRES',
                            'reprod_par:T2DRES',
                            eps=[1e-4])

        # Epsilon for concatenation case
        self.check_epsilons('par:T2DRES',
                            'concat:T2DRES',
                            eps=[1e-12])

    def _post(self):
        """
        Post-treatment processes
        """
        from postel.plot_vnv import vnv_plot1d_polylines, vnv_plot2d, vnv_plot3d
        # Getting the name of the result file of the sequential run of
        # vnv_thompson
        res_file = self.get_study_file('qua_seq:T2DRES')
        bnd_file = self.get_study_file('qua_seq:T2DCLI')
        res_seq = TelemacFile(res_file, bnd_file=bnd_file)

        # Plotting water depth over polyline for time step 0
        vnv_plot1d_polylines(\
            'WATER DEPTH',
            res_seq,
            legend_labels='initial elevation',
            fig_size=(8, 2),
            record=0,
            poly=[[0., 10.], [20., 10.]],
            poly_number=[50],
            fig_name='img/InitialElevation')

        # plotting mesh
        vnv_plot2d(\
            '',
            res_seq,
            record=0,
            fig_size=(5, 5),
            fig_name="img/Mesh",
            plot_mesh=True)

        for record in [0, 3, 6, 9, 12, 15, 18, 20]:
            # Plotting sclar map of water depth for some time steps
            fig_name = "img/t2d_gouttedo_qua_time{}".format(record)
            vnv_plot2d(\
                'WATER DEPTH', res_seq,
                record=record,
                fig_size=(7, 6),
                fig_name=fig_name,
                cbar_label='H',
                contours=True,
                annotate_time=True,
                filled_contours=True)

            # Plotting 3d sclar map of water depth for some time steps
            fig_name = "img/t2d_gouttedo_qua_time{}_3d".format(record)
            vnv_plot3d(\
                'WATER DEPTH', res_seq,
                record=record,
                fig_size=(8, 6),
                fig_name=fig_name,
                zlim=[0., 4.5],
                annotate_time=True,
                cbar_label='H')

        res_seq.close()
