# Simulation RenPy
This project allows to run a simulation of characters where they can act depending on their current set of attributes, move between different places and interact with each other. To create new objects for simulation, use another project [SimulationAdmin](https://github.com/oceanlazy/simulation-renpy-admin).  

## Installation
Copy this project to the directory with other RenPy projects. Tested for 8.0.0 version.  
  
If you are using python3 ignore this step. This project is compatible with python2 but to use it you will need to install `future` library:
```bash
pip install future
```
  
Don't forget to set the `DEBUG` flag to `False` when you use it in your game.

## Testing
To view an example of a simulation: 
```bash
python kernel/tests/test_simulation.py
```
The data for the demo simulation is already in this repository(`db` directory), you are completely free to delete it and create new one using `simulation-admin`.

### line-profiler
To measure the speed of individual functions, use `line-profiler`.
```bash
pip install line-profiler
```
Then decorate some function:
```python
@profiler
def process_effects(self):
    ...
```