"""Pytest fixtures — put the desk root on sys.path for absolute imports."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
