#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
============================================
QMC Hirsch - Fye Impurity solver for a Dimer
============================================

To treat the dimer in a Bethe lattice and solve it using the Hirsch - Fye
Quantum Monte Carlo algorithm
"""

from __future__ import division, absolute_import, print_function
import numpy as np
import sys
import os
import json
from mpi4py import MPI
import dmft.common as gf
import dmft.hirschfye as hf
import dmft.RKKY_dimer as dimer
import dmft.plot.hf_dimer as pd
comm = MPI.COMM_WORLD


def dmft_loop_pm(simulation, U, g_iw_start=None):
    """Implementation of the solver"""
    setup = {'t':         0.5,
             'BANDS':     1,
             'SITES':     2,
             }

    if simulation['new_seed']:
        if comm.rank == 0:
            hf.set_new_seed(simulation, ['gtau_d', 'gtau_o'])
        simulation['U'] = simulation['new_seed'][1]
        return

    setup.update(simulation)
    setup['dtau_mc'] = setup['BETA']/2./setup['N_MATSUBARA']
    current_u = 'U'+str(U)
    setup['simt'] = 'PM' # simulation type ParaMagnetic

    tau, w_n = gf.tau_wn_setup(setup)
    intm = hf.interaction_matrix(setup['BANDS'])
    setup['n_tau_mc'] = len(tau)
    mu, tp = setup['MU'], setup['tp']
    giw_d, giw_o = dimer.gf_met(w_n, mu, tp, 0.5, 0.)

    if g_iw_start is not None:
        giw_d, giw_o = g_iw_start

    save_dir = os.path.join(setup['ofile'].format(**setup), current_u)
    try:  # try reloading data from disk
        with open(save_dir + '/setup', 'r') as conf:
            last_loop = json.load(conf)['last_loop']
        gtu = np.load(os.path.join(save_dir,
                                    'it{:03}'.format(last_loop),
                                    'gtau_up.npy')).reshape(2, 2, -1)
        gtd = np.load(os.path.join(save_dir,
                                    'it{:03}'.format(last_loop),
                                    'gtau_dw.npy')).reshape(2, 2, -1)

        gtau_d = -0.25 * (gtu[0, 0] + gtu[1, 1] + gtd[0, 0] + gtd[1, 1])
        gtau_o = -0.25 * (gtu[1, 0] + gtu[0, 1] + gtd[1, 0] + gtd[0, 1])

        giw_d = gf.gt_fouriertrans(gtau_d, tau, w_n,
                                   [1., -mu, U**2/4 +
                                    tp**2+mu**2])

        giw_o = gf.gt_fouriertrans(gtau_o, tau, w_n,
                                   [0., tp, -10.*mu*tp**2])

        last_loop += 1
    except (IOError, KeyError, ValueError):  # if no data clean start
        last_loop = 0

    V_field = hf.ising_v(setup['dtau_mc'], U,
                         L=setup['SITES']*setup['n_tau_mc'],
                         polar=setup['spin_polarization'])


    for iter_count in range(last_loop, last_loop + setup['Niter']):
        work_dir = os.path.join(save_dir, 'it{:03}'.format(iter_count))
        setup['work_dir'] = work_dir

        if comm.rank == 0:
            print('On loop', iter_count, 'beta', setup['BETA'],
                  'U', U, 'tp', tp)

        # Cleaning the input to half-filling
        giw_d.real = 0.
        giw_o.imag = 0.

        # Bethe lattice bath
        g0iw_d, g0iw_o = dimer.self_consistency(1j*w_n, giw_d, giw_o, mu, tp, 0.25)

        g0tau_d = gf.gw_invfouriertrans(g0iw_d, tau, w_n,
                                        [1., -mu, tp**2+mu**2])
        g0tau_o = gf.gw_invfouriertrans(g0iw_o, tau, w_n,
                                        [0., tp, -10.*mu*tp**2])

        # Cleaning to casual
        g0tau_d[g0tau_d > -1e-7] = -1e-7

        # Impurity solver
        g0t = np.array([[g0tau_d, g0tau_o], [g0tau_o, g0tau_d]])

        gtu, gtd = hf.imp_solver([g0t]*2, V_field, intm, setup)
        gtau_d = -0.25 * (gtu[0, 0] + gtu[1, 1] + gtd[0, 0] + gtd[1, 1])
        gtau_o = -0.25 * (gtu[1, 0] + gtu[0, 1] + gtd[1, 0] + gtd[0, 1])

        giw_d = gf.gt_fouriertrans(gtau_d, tau, w_n,
                                   [1., -mu, U**2/4 +
                                    tp**2+mu**2])

        giw_o = gf.gt_fouriertrans(gtau_o, tau, w_n,
                                   [0., tp, -10.*mu*tp**2])


        # Save output
        if comm.rank == 0:
            np.save(work_dir+'/gtau_up', gtu.reshape(4, -1))
            np.save(work_dir+'/gtau_dw', gtd.reshape(4, -1))
            with open(save_dir + '/setup', 'w') as conf:
                setup['last_loop'] = iter_count
                json.dump(setup, conf, indent=2)
        sys.stdout.flush()


if __name__ == "__main__":
    parser = hf.do_input('DMFT loop for Hirsh-Fye dimer lattice')
    parser.add_argument('-tp', type=float, default=.25,
                        help='Dimerization strength')
    parser.add_argument('-df', '--double_flip_prob', type=float, default=0.,
                        help='Probability for double spin flip on equal sites')

    SETUP = vars(parser.parse_args())
    for U in SETUP['U']:
        dmft_loop_pm(SETUP, U)
