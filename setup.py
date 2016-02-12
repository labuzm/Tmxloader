#!/usr/bin/env python

from distutils.core import setup
from tmxloader import __VERSION__

setup(
    name='tmxloader',
    version=__VERSION__,
    description='Simple library for loading .tmx files',
    author='Marcin Labuz',
    author_email='labuzm@gmail.com',
    packages=['tmxloader']

)
