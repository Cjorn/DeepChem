deepchem
=============

Deep Learning Toolchain for Cheminformatics and Protein Analysis

Requirements
------------
* [rdkit](http://www.rdkit.org/docs/Install.html)
* [sklearn](https://github.com/scikit-learn/scikit-learn.git)
* [numpy](https://store.continuum.io/cshop/anaconda/)
* [keras](http://keras.io)

Linux (64-bit) Installation 
------------------

```deepchem``` currently requires Python 2.7

###Anaconda 2.7
Download the **64-bit Python 2.7** version of Anaconda for linux [here](https://www.continuum.io/downloads#_unix).

Follow the [installation instructions](http://docs.continuum.io/anaconda/install#linux-install)

###openbabel
```bash
conda install -c omnia openbabel
```  

Follow the onscreen installation instructions

###rdkit
```bash
conda install -c omnia rdkit
```

Follow the onscreen installation instructions

###keras
Clone the keras git repository
```bash
git clone https://github.com/fchollet/keras.git
```

Cd into the keras directory and execute
```bash
python setup.py install
```

###deepchem
Clone the deep_chem git repository
```bash
git clone https://github.com/pandegroup/deepchem.git
```

Cd into the deepchem directory and execute 
```bash
python setup.py develop
```
