import os
import curses
import pycfg
from pyarch import load_binary_into_memory
from pyarch import cpu_t

PYOS_TASK_STATE_READY = 0
PYOS_TASK_STATE_EXECUTING = 1


class task_t:
    def __init__(self):
        self.regs = [0, 0, 0, 0, 0, 0, 0, 0]
        self.reg_pc = 0
        self.stack = 0
        self.paddr_offset = 0
        self.paddr_max = 0
        self.bin_name = ""
        self.bin_size = 0
        self.tid = 0
        self.state = PYOS_TASK_STATE_READY

    def get_reg(self, reg):
        return self.regs[reg]

    def set_reg(self, reg, value):
        self.regs[reg] = value

    def get_pc(self):
        return self.reg_pc

    def set_pc (self, pc):
        self.reg_pc = pc

    def get_paddr_offset(self):
        return self.paddr_offset

    def get_paddr_max(self):
        return self.paddr_max


class os_t:
    def __init__(self, cpu, memory, terminal):
        self.cpu = cpu
        self.memory = memory
        self.terminal = terminal

        self.addr_offset_free = 0
        self.addr_max_free = memory.get_size()

        self.terminal.enable_curses()

        self.console_str = ""

        self.the_task = None
        self.next_task_id = 0

        self.current_task = None
        self.next_sched_task = 0
        self.idle_task = None
        self.idle_task = self.load_task("idle.bin")

        if self.idle_task is None:
            self.panic("could not load idle.bin task")

        self.sched(self.idle_task)

        self.terminal.console_print("this is the console, type the commands here\n")

    def get_addr_offset_free(self):
        return self.addr_offset_free

    def get_addr_max_free(self):
        return self.addr_max_free

    def set_addr_offset_free(self, addr_offset):
        self.addr_offset_free = addr_offset

    def set_addr_max_free(self, addr_max):
        self.addr_max_free = addr_max

    def load_task(self, bin_name):
        if not os.path.isfile(bin_name):
            self.printk("file " + bin_name + " does not exists")
            return None
        if (os.path.getsize(bin_name) % 2) == 1:
            self.printk("file size of " + bin_name + " must be even")
            return None

        task = task_t()
        task.bin_name = bin_name
        task.bin_size = os.path.getsize(bin_name) / 2  # 2 bytes = 1 word

        task.paddr_offset, task.paddr_max = self.allocate_contiguos_physical_memory_to_task(task.bin_size, task)

        if task.paddr_offset == -1:
            return None

        task.regs = [0, 0, 0, 0, 0, 0, 0, 0]
        task.reg_pc = 1
        task.stack = 0
        task.state = PYOS_TASK_STATE_READY

        self.printk("allocated physical addresses " + str(task.paddr_offset) + " to " + str(
            task.paddr_max) + " for task " + task.bin_name + " (" + str(
            self.get_task_amount_of_memory(task)) + " words) (binary has " + str(task.bin_size) + " words)")

        self.read_binary_to_memory(task.paddr_offset, task.paddr_max, bin_name)

        self.printk("task " + bin_name + " successfully loaded")

        task.tid = self.next_task_id
        self.next_task_id = self.next_task_id + 1

        # self.tasks.append( task )
        return task

    def read_binary_to_memory(self, paddr_offset, paddr_max, bin_name):
        bpos = 0
        paddr = paddr_offset
        bin_size = os.path.getsize(bin_name) / 2
        i = 0
        with open(bin_name, "rb") as f:
            while True:
                byte = f.read(1)
                if not byte:
                    break
                byte = ord(byte)
                if bpos == 0:
                    lower_byte = byte
                else:
                    word = lower_byte | (byte << 8)
                    if paddr > paddr_max:
                        self.panic(
                            "something really bad happenned when loading " + bin_name + " (paddr > task.paddr_max)")
                    self.memory.write(paddr, word)
                    paddr = paddr + 1
                    i = i + 1
                bpos = bpos ^ 1

        if i != bin_size:
            self.panic("something really bad happenned when loading " + bin_name + " (i != task.bin_size)")

    def sched(self, task):
        if self.current_task is not None:
            self.panic(
                "current_task must be None when scheduling a new one (current_task=" + self.current_task.bin_name + ")")
        if task.state != PYOS_TASK_STATE_READY:
            self.panic("task " + task.bin_name + " must be in READY state for being scheduled (state = " + str(
                task.state) + ")")

        # TODO
        # Escrever no processador os registradores de proposito geral salvos na task struct
        i_reg = 0
        while i_reg < pycfg.NREGS:
            self.cpu.set_reg(i_reg, task.get_reg(i_reg))
            i_reg += 1

        # Escrever no processador o PC salvo na task struct
        self.cpu.set_pc(task.get_pc())

        # Atualizar estado do processo
        task.state = PYOS_TASK_STATE_EXECUTING

        # Escrever no processador os registradores que configuram a memoria virtual, salvos na task struct
        self.cpu.set_paddr_offset(task.get_paddr_offset())
        self.cpu.set_paddr_max(task.get_paddr_max())

        self.current_task = task
        self.printk("scheduling task " + task.bin_name)

    def get_task_amount_of_memory(self, task):
        return task.paddr_max - task.paddr_offset + 1

    # allocate contiguos physical addresses that have $words
    # returns the addresses of the first and last words to be used by the process
    # -1, -1 if cannot find

    def allocate_contiguos_physical_memory_to_task(self, words, task):
        # TODO
        # Localizar um bloco de memoria livre para armazenar o processo
        aux_addr_offset = self.get_addr_offset_free()
        aux_addr_max = aux_addr_offset + words

        # Retornar tupla <primeiro endereco livre>, <ultimo endereco livre>
        if task.bin_name == "idle.bin":
            self.set_addr_offset_free(aux_addr_max + 1)
            return aux_addr_offset, aux_addr_max
        else:
            free_space = aux_addr_max < self.get_addr_max_free()
            if free_space:
                return aux_addr_offset, aux_addr_max

        # if we get here, there is no free space to put the task
        self.printk("could not allocate memory to task " + task.bin_name)
        return -1, -1

    def printk(self, msg):
        self.terminal.kernel_print("kernel: " + msg + "\n")

    def panic(self, msg):
        self.terminal.end()
        self.terminal.dprint("kernel panic: " + msg)
        self.cpu.cpu_alive = False

    # cpu.cpu_alive = False

    def interrupt_keyboard(self):
        key = self.terminal.get_key_buffer()

        if ((key >= ord('a')) and (key <= ord('z'))) or ((key >= ord('A')) and (key <= ord('Z'))) or (
                (key >= ord('0')) and (key <= ord('9'))) or (key == ord(' ')) or (key == ord('-')) or (
                key == ord('_')) or (key == ord('.')):
            self.console_str = self.console_str + chr(key)
            self.terminal.console_print("\r" + self.console_str)
        elif key == curses.KEY_BACKSPACE:
            self.console_str = self.console_str[:-1]
            self.terminal.console_print("\r" + self.console_str)
        elif (key == curses.KEY_ENTER) or (key == ord('\n')):
            self.interpret_cmd(self.console_str)
            self.console_str = ""

    def interpret_cmd(self, cmd):
        if cmd == "bye":
            self.cpu.cpu_alive = False
        elif cmd == "tasks":
            self.task_table_print()
        elif cmd[:3] == "run":
            if (self.the_task is not None):
                self.terminal.console_print("error: binary " + self.the_task.bin_name + " is already running\n")
            else:
                bin_name = cmd[4:]
                self.terminal.console_print("\rrun binary " + bin_name + "\n")
                task = self.load_task(bin_name)
                if task is not None:
                    self.the_task = task;
                    self.un_sched(self.idle_task)
                    self.sched(self.the_task)
                else:
                    self.terminal.console_print("error: binary " + bin_name + " not found\n")
        else:
            self.terminal.console_print("\rinvalid cmd " + cmd + "\n")

    def task_table_print(self):
        self.terminal.console_print("task table:\n")
        self.terminal.console_print("id   state   sp   baddr   mem   binary\n")

        tasks = [
            task for task in [self.current_task, self.the_task, self.idle_task] if task is not None
        ]

        for task in tasks:
            marker = " *" if task == self.the_task else ""
            task_info = "{tid}   {state}   {pc}   {stack}   {offset}   {max}   {bin_name}{marker}\n".format(
                tid=task.tid,
                state="EXEC" if task == self.current_task else "READY",
                pc=task.reg_pc,
                stack=task.stack,
                offset=task.paddr_offset,
                max=task.paddr_max,
                bin_name=task.bin_name,
                marker=marker
            )
            self.terminal.console_print(task_info)

    def terminate_unsched_task(self, task):
        if task.state == PYOS_TASK_STATE_EXECUTING:
            self.panic("impossible to terminate a task that is currently running")
        if task == self.idle_task:
            self.panic("impossible to terminate idle task")
        if task is not self.the_task:
            self.panic("task being terminated should be the_task")

        self.the_task = None
        self.printk("task " + task.bin_name + " terminated")

    def un_sched(self, task):
        if task.state != PYOS_TASK_STATE_EXECUTING:
            self.panic("task " + task.bin_name + " must be in EXECUTING state for being scheduled (state = " + str(
                task.state) + ")")
        if task is not self.current_task:
            self.panic(
                "task " + task.bin_name + " must be the current_task for being scheduled (current_task = " + self.current_task.bin_name + ")")

        # TODO
        # Salvar na task struct
        # - registradores de proposito geral
        i_reg = 0
        while i_reg < pycfg.NREGS:
            task.set_reg(i_reg, self.cpu.get_reg(i_reg))
            i_reg += 1

        # - PC
        task.set_pc(self.cpu.get_pc())

        # Atualizar o estado do processo
        task.state = PYOS_TASK_STATE_READY

        self.current_task = None
        self.printk("unscheduling task " + task.bin_name)

    def virtual_to_physical_addr(self, task, vaddr):
        return task.paddr_offset + vaddr

    def check_valid_vaddr(self, task, vaddr):
        paddr = self.virtual_to_physical_addr(self.current_task, vaddr)
        if paddr > task.paddr_max:
            return False
        else:
            return True

    def handle_gpf(self, error):
        task = self.current_task
        self.printk("gpf task " + task.bin_name + ": " + error)
        self.un_sched(task)
        self.terminate_unsched_task(task)
        self.sched(self.idle_task)

    def interrupt_timer(self):
        self.printk("timer interrupt NOT IMPLEMENTED")

    def handle_interrupt(self, interrupt):
        if interrupt == pycfg.INTERRUPT_MEMORY_PROTECTION_FAULT:
            self.handle_gpf("invalid memory address")
        elif interrupt == pycfg.INTERRUPT_KEYBOARD:
            self.interrupt_keyboard()
        elif interrupt == pycfg.INTERRUPT_TIMER:
            self.interrupt_timer()
        else:
            self.panic("invalid interrupt " + str(interrupt))

    def memory_load(self, task, vaddr):
        if self.check_valid_vaddr(task, vaddr):
            paddr = self.virtual_to_physical_addr(task, vaddr)
            return self.memory.read(paddr)
        else:
            return self.handle_gpf("invalid virtual address")

    def get_str_stored(self, task, vaddr):
        # Get string stored in virtual address
        value_str = ""
        chr_stored = self.memory_load(task, vaddr)

        i_vaddr = vaddr
        while chr_stored:
            value_str += chr(chr_stored)
            i_vaddr += 1
            chr_stored = self.memory_load(task, i_vaddr)

        return value_str

    def break_line_app(self):
        # Enter line console
        self.terminal.app_print("\n")
        return

    def get_int_stored(self, i_reg):
        # Get integer stored in virtual address
        value_int = self.cpu.get_reg(i_reg)
        return str(value_int)

    def syscall(self):
        service = self.cpu.get_reg(0)
        task = self.current_task

        if service == 0:
            self.printk("app " + self.current_task.bin_name + " request finish")
            self.un_sched(task)
            self.terminate_unsched_task(task)
            self.sched(self.idle_task)

        # TODO
        # Implementar aqui as outras chamadas de sistema
        if service == 0:
            self.printk("app " + self.current_task.bin_name + " request finish")
            self.un_sched(task)
            self.terminate_unsched_task(task)
            self.sched(self.idle_task)
        elif service == 1:
            # Servico de impressao de string
            self.terminal.app_print(self.get_str_stored(task, self.cpu.get_reg(1)))
        elif service == 2:
            self.break_line_app()
        elif service == 3:
            # Servico de impressao de inteiro
            self.terminal.app_print(self.get_int_stored(1))

        else:
            self.handle_gpf("invalid syscall " + str(service))
