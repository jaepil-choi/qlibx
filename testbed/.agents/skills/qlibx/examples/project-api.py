"""Load only public project surfaces."""

from qlibx import Project
from qlibx.data import ConfigDrivenDataLoader
from qlibx.research import ResearchCatalog

project = Project.load(".")
loader = ConfigDrivenDataLoader.from_project(project)
research = ResearchCatalog.from_project(project)
