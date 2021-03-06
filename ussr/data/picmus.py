import io
import os
import re
import shutil
import urllib.request
import zipfile

import h5py
import numpy as np

from ussr.probe import L11Probe
from ussr.sequence import USSequence, PWSequence
from ussr.utils import ui


def download_2017(export_path, signal_selection=None, pht_selection=None, transmission_selection=None,
                  pw_number_selection=None):
    base_url = 'https://www.creatis.insa-lyon.fr/EvaluationPlatform/picmus/dataset/'

    # Default parameters
    if signal_selection is None:
        signal_selection = ['rf']  # 'rf' | 'iq'
    if pht_selection is None:
        pht_selection = ['numerical', 'in_vitro_type1', 'in_vitro_type2', 'in_vitro_type3']  # 1: numerical | 2: in_vitro_type1 | 3: in_vitro_type2 | 4: in_vitro_type3
    if transmission_selection is None:
        transmission_selection = ['transmission_1']  # 1: regular = transmission_1 | 2: dichotomous = transmission_2
    if pw_number_selection is None:
        pw_number_selection = [5]  # An odd value between 1 and 75

    # Valid optional input paramters
    # TODO: add check of input parameters
    valid_sel_signal = ['rf', 'iq']
    valid_sel_pht = ['numerical', 'in_vitro_type1', 'in_vitro_type2', 'in_vitro_type3']
    valid_sel_transmission = ['transmission_1', 'transmission_2']
    valid_sel_PW_number = list(range(1, 76, 2))

    # Get all valid data file list
    #   Data files start with `dataset` and end with `.hdf5`
    response = urllib.request.urlopen(base_url)
    index = response.read().decode('utf-8')
    reg_data = re.compile(r'(?<=<a href=")dataset\w*\.hdf5(?=">)')
    data_list = reg_data.findall(index)

    # Set download list
    reg_signal = re.compile('\w*_(' + '|'.join(signal_selection) + ')_\w*')
    reg_pht = re.compile('\w*_(' + '|'.join(pht_selection) + ')_\w*')
    reg_transmission = re.compile('\w*_(' + '|'.join(transmission_selection) + ')_\w*')
    reg_PW_number = re.compile('\w*_nbPW_(' + '|'.join(map(str, pw_number_selection)) + ')\.hdf5')
    data_down_list = [f for f in data_list if reg_signal.search(f) is not None
                      and reg_pht.search(f) is not None
                      and reg_transmission.search(f) is not None
                      and reg_PW_number.search(f) is not None]

    # Get scanning region file
    reg_scan = re.compile(r'(?<=<a href=")scanning\w*.hdf5(?=">)')
    scan_list = reg_scan.findall(index)

    # Download all files and save
    down_list = [*data_down_list, *scan_list]

    if not os.path.exists(export_path):
        os.makedirs(export_path)

    for filename in down_list:

        export_file_path = os.path.abspath(os.path.join(export_path, filename))

        if not os.path.exists(export_file_path):
            data_url = base_url + filename
            with open(export_file_path, 'wb') as export_file:
                ui.download_file(data_url, export_file)
        else:
            print('{} already exists in {}'.format(filename, export_path))


def download_in_vivo_2016(export_path):
    # Base download url
    base_url = 'https://www.creatis.insa-lyon.fr/Challenge/IEEE_IUS_2016/download'

    # Exported in vivo file names
    file_check_list = ['carotid_cross_expe_dataset_rf.hdf5', 'carotid_cross_expe_scan.hdf5',
                       'carotid_long_expe_dataset_rf.hdf5', 'carotid_long_expe_scan.hdf5']

    # In vivo data
    # <a href="https://www.creatis.insa-lyon.fr/Challenge/IEEE_IUS_2016/sites/www.creatis.insa-lyon.fr.Challenge.IEEE_IUS_2016/files/in_vivo.zip">
    response = urllib.request.urlopen(base_url)
    index = response.read().decode('utf-8')
    reg_data = re.compile(r'(?<=<a href=").*in_vivo\.zip(?=">)')
    data_url = reg_data.findall(index)[0]

    # Check if files already exist
    if all([os.path.exists(os.path.join(export_path, f)) for f in file_check_list]):
        print('PICMUS 2016 in-vivo data already exist in {}'.format(export_path))
        return

    # Create directories if required
    if not os.path.exists(export_path):
        os.makedirs(export_path)

    # Download, extract and save files
    with io.BytesIO() as dlbuf:
        ui.download_file(data_url, dlbuf)
        with zipfile.ZipFile(dlbuf, mode='r') as myzip:
            # Only extract files from `file_check_list`
            data_namelist = [nm for nm in myzip.namelist() if os.path.basename(nm) in file_check_list]
            # Extract .zip in export_path (without keeping directory structure)
            for file in data_namelist:
                filename = os.path.basename(file)
                with myzip.open(file) as zf, open(os.path.join(export_path, filename), 'wb') as fdst:
                    shutil.copyfileobj(zf, fdst)


def import_sequence(path, remove_tgc=False, selected_indexes=None):

    # Create standard configuration L11 probe
    probe = L11Probe()

    # Open HDF5 file
    if not os.path.exists(path):
        raise FileNotFoundError('{file} does not exist'.format(file=path))

    with h5py.File(path) as h5_file:
        # Extract sequence information
        name = os.path.splitext(os.path.basename(path))[0]
        all_angles = h5_file['US']['US_DATASET0000']['angles'].value
        sampling_frequency = float(h5_file['US']['US_DATASET0000']['sampling_frequency'].value)
        transmit_frequency = sampling_frequency / 4  # specific to Verasonics
        mean_sound_speed = float(h5_file['US']['US_DATASET0000']['sound_speed'].value)

        # Extract raw data
        #   Extract the 'real' values only since RF data is considered
        #   data: shape=(angle_number, transducer_number, sample_number)
        raw_data = h5_file['US']['US_DATASET0000']['data']['real'].value.astype(np.float32)
        if all_angles.shape[0] is 1:
            all_data = [raw_data]
        else:
            all_data = [d for d in raw_data]

        #   Initial times are always 0 in the case of PICMUS, hence only one is given.
        #   It is then duplicated to have the same size as `angles`
        initial_time = h5_file['US']['US_DATASET0000']['initial_time'].value
        all_initial_times = np.zeros(all_angles.shape) + initial_time

        # Selected indexes
        if selected_indexes is not None:
            data = [all_data[ind] for ind in selected_indexes]
            angles = [all_angles[ind] for ind in selected_indexes]
            initial_times = [all_initial_times[ind] for ind in selected_indexes]
        else:
            data = all_data
            angles = all_angles
            initial_times = all_initial_times

        # Additional required sequence information (see website)
        transmit_wave = 'square'
        transmit_cycles = 2.5
        medium_attenuation = 0.5

        # Create PWSequence object
        sequence = PWSequence(name=name,
                              probe=probe,
                              sampling_frequency=sampling_frequency,
                              transmit_frequency=transmit_frequency,
                              transmit_wave=transmit_wave,
                              transmit_cycles=transmit_cycles,
                              mean_sound_speed=mean_sound_speed,
                              medium_attenuation=medium_attenuation,
                              angles=angles,
                              initial_times=initial_times,
                              data=data)

        # Remove Time Gain Compensation
        if remove_tgc:
            if not (name == 'carotid_cross_expe_dataset_rf' or name == 'carotid_long_expe_dataset_rf'):
                # Remove PICMUS17 TGC
                tgc_factors = _tgc_factor(sequence)
                for tgc_fact, data in zip(tgc_factors, sequence.data):
                    data /= tgc_fact

    return sequence


def _tgc_factor(sequence):
    """
    Time Gain Compensation (TGC) factor as provided by PICMUS creators
    :return: gain
    """
    if isinstance(sequence, USSequence):
        pass
    else:
        raise TypeError('`sequence` must be an instance of class `USSequence`')

    # Reference depth and gain
    wavelengths = np.array([0, 54.8571, 109.7143, 164.5714, 219.4286, 274.2857, 329.1429, 384], dtype=np.float32)
    depth_dp = wavelengths * sequence.wavelength
    gain_dp = np.array([139, 535, 650, 710, 770, 932, 992, 1012], dtype=np.float32)

    # Interpolation on `depth` for each data
    gain = []
    for initial_time, data in zip(sequence.initial_times, sequence.data):
        sample_number = data.shape[-1]
        depth = initial_time * sequence.mean_sound_speed / 2 + np.arange(
            sample_number) * sequence.mean_sound_speed / (2 * sequence.sampling_frequency)
        gain.append(np.interp(depth, depth_dp, gain_dp, left=gain_dp[0], right=gain_dp[-1]))

    return gain


